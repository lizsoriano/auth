-- =====================================================================
-- 010 · Microservicio Pagos: pagos y actualización del estado del pedido
-- ---------------------------------------------------------------------
-- Tabla nueva: payments. Registrar un pago es ATÓMICO: valida el pedido, inserta el
-- pago y pasa el pedido a "pagado" en la misma transacción (por eso es una función SQL y no
-- una llamada HTTP entre servicios).
--
-- Idempotencia: payments.idempotency_key es UNIQUE. Repetir la misma clave para el mismo pedido
-- devuelve el pago ya registrado (duplicated = true) y NO cobra dos veces; la misma clave para
-- otro pedido es un error. Un pedido solo puede tener un pago.
--
-- No hay pasarela real: el método (tarjeta/transferencia/efectivo) solo se registra.
--
-- Códigos SQLSTATE propios:
--   PG001 pedido no existe (o no es tuyo) · PG002 el pedido no está pendiente de pago
--   PG003 el monto no coincide con el total · PG004 clave de idempotencia usada en otro pedido
--   PG005 datos inválidos · PG006 pago no existe
-- Requiere 006, 007 y 009. Ejecutar como library_user (dueño).
-- =====================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF to_regclass('public.orders') IS NULL THEN
    RAISE EXCEPTION 'Ejecuta antes 009_pedidos.sql';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pagos_service_user') THEN
    RAISE EXCEPTION 'Falta el rol pagos_service_user: ejecuta antes 007_service_db_roles.sql (como postgres)';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS payments (
    payment_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL,
    user_id bigint NOT NULL,
    amount numeric(12, 2) NOT NULL,
    method varchar(20) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'aprobado',
    idempotency_key varchar(80) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_payments_idempotency_key UNIQUE (idempotency_key),
    CONSTRAINT uq_payments_order UNIQUE (order_id),
    CONSTRAINT fk_payments_order FOREIGN KEY (order_id) REFERENCES orders (order_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_payments_user FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_payments_amount_positive CHECK (amount > 0),
    CONSTRAINT ck_payments_method CHECK (method IN ('tarjeta', 'transferencia', 'efectivo')),
    CONSTRAINT ck_payments_status CHECK (status IN ('aprobado')),
    CONSTRAINT ck_payments_key_not_blank CHECK (btrim(idempotency_key) <> '')
);
CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments (user_id);

CREATE OR REPLACE FUNCTION fn_pago_json(p_payment_id bigint)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT jsonb_build_object(
               'payment_id', p.payment_id, 'order_id', p.order_id, 'user_id', p.user_id,
               'amount', p.amount, 'method', p.method, 'status', p.status,
               'order_status', s.name, 'created_at', p.created_at)
      FROM payments p
      JOIN orders o ON o.order_id = p.order_id
      JOIN order_statuses s ON s.status_id = o.status_id
     WHERE p.payment_id = p_payment_id;
$$;

-- p_privileged = true (admin/staff) puede pagar cualquier pedido; false: solo los del propio p_actor_user_id.
CREATE OR REPLACE FUNCTION fn_pagos_registrar(
    p_order_id bigint, p_actor_user_id bigint, p_privileged boolean,
    p_method varchar, p_amount numeric, p_idempotency_key varchar)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_order orders%ROWTYPE;
    v_existing payments%ROWTYPE;
    v_payment_id bigint;
BEGIN
    IF coalesce(btrim(p_idempotency_key), '') = '' OR length(p_idempotency_key) > 80 THEN
        RAISE EXCEPTION 'La clave de idempotencia es obligatoria (máximo 80 caracteres)' USING ERRCODE = 'PG005';
    END IF;
    IF p_method IS NULL OR p_method NOT IN ('tarjeta', 'transferencia', 'efectivo') THEN
        RAISE EXCEPTION 'method debe ser tarjeta, transferencia o efectivo' USING ERRCODE = 'PG005';
    END IF;

    SELECT * INTO v_order FROM orders WHERE order_id = p_order_id FOR UPDATE;
    IF NOT FOUND OR (NOT coalesce(p_privileged, false) AND v_order.user_id <> p_actor_user_id) THEN
        RAISE EXCEPTION 'No existe el pedido %', p_order_id USING ERRCODE = 'PG001';
    END IF;

    SELECT * INTO v_existing FROM payments WHERE idempotency_key = btrim(p_idempotency_key);
    IF FOUND THEN
        IF v_existing.order_id <> p_order_id THEN
            RAISE EXCEPTION 'Esa clave de idempotencia ya se usó en otro pedido' USING ERRCODE = 'PG004';
        END IF;
        RETURN fn_pago_json(v_existing.payment_id) || jsonb_build_object('duplicated', true);
    END IF;

    IF v_order.status_id <> 1 THEN
        RAISE EXCEPTION 'El pedido % no está pendiente de pago', p_order_id USING ERRCODE = 'PG002';
    END IF;
    IF p_amount IS NULL OR p_amount <> v_order.total THEN
        RAISE EXCEPTION 'El monto debe ser exactamente % (total del pedido)', v_order.total USING ERRCODE = 'PG003';
    END IF;

    INSERT INTO payments (order_id, user_id, amount, method, idempotency_key)
    VALUES (p_order_id, p_actor_user_id, v_order.total, p_method, btrim(p_idempotency_key))
    RETURNING payment_id INTO v_payment_id;
    UPDATE orders SET status_id = 2 WHERE order_id = p_order_id;
    RETURN fn_pago_json(v_payment_id) || jsonb_build_object('duplicated', false);
END $$;

-- p_user_id NULL = todos (admin/staff); un número = solo pagos de pedidos de ese usuario.
CREATE OR REPLACE FUNCTION fn_pagos_listar(
    p_user_id bigint, p_order_id bigint, p_limit integer DEFAULT 50, p_offset integer DEFAULT 0)
RETURNS TABLE (payment_id bigint, order_id bigint, user_id bigint, amount numeric, method varchar,
               status varchar, created_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT p.payment_id, p.order_id, p.user_id, p.amount, p.method, p.status, p.created_at
      FROM payments p JOIN orders o ON o.order_id = p.order_id
     WHERE (p_user_id IS NULL OR o.user_id = p_user_id)
       AND (p_order_id IS NULL OR p.order_id = p_order_id)
     ORDER BY p.payment_id DESC
     LIMIT greatest(least(coalesce(p_limit, 50), 200), 1)
    OFFSET greatest(coalesce(p_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION fn_pago_obtener(p_payment_id bigint, p_actor_user_id bigint)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v jsonb := fn_pago_json(p_payment_id);
BEGIN
    IF v IS NULL
       OR (p_actor_user_id IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM orders o WHERE o.order_id = (v->>'order_id')::bigint AND o.user_id = p_actor_user_id)) THEN
        RAISE EXCEPTION 'No existe el pago %', p_payment_id USING ERRCODE = 'PG006';
    END IF;
    RETURN v;
END $$;

-- ============================ PERMISOS ===============================
DO $$
DECLARE
    r record;
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO pagos_service_user', current_database());
    GRANT USAGE ON SCHEMA public TO pagos_service_user;
    FOR r IN SELECT p.oid::regprocedure AS sig
               FROM pg_proc p
              WHERE p.pronamespace = 'public'::regnamespace AND p.proname LIKE 'fn\_pago%' LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', r.sig);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO pagos_service_user', r.sig);
    END LOOP;
END $$;

COMMIT;
