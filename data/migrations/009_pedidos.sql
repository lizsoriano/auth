-- =====================================================================
-- 009 · Microservicio Pedidos: pedidos, líneas, estados y stock
-- ---------------------------------------------------------------------
-- Tablas nuevas (nadie más las usa): order_statuses, orders, order_items.
-- books NO cambia de forma: solo baja/sube books.stock dentro de funciones.
--
-- Estados: 1 pendiente · 2 pagado (lo marca fn_pagos_registrar, 010) · 3 enviado · 4 cancelado.
-- Transiciones permitidas aquí: pendiente -> cancelado (repone stock) y pagado -> enviado.
--
-- Crear un pedido es ATÓMICO: bloquea las filas de books en orden de book_id (sin
-- interbloqueos), exige stock suficiente y descuenta; si algo falla, no queda nada.
-- Las funciones reciben p_actor_user_id: NULL = administrador/staff (ven todo);
-- un número = cliente (solo ve lo suyo; lo ajeno responde "no existe" para no revelarlo).
--
-- Códigos SQLSTATE propios:
--   PD001 datos inválidos · PD002 stock insuficiente · PD003 pedido no existe
--   PD004 transición no permitida · PD005 ISBN inexistente · PD007 usuario inexistente o inactivo
-- Requiere 006 y 007. Ejecutar como library_user (dueño).
-- =====================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF to_regclass('public.roles') IS NULL THEN
    RAISE EXCEPTION 'Ejecuta antes 006_roles.sql';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pedidos_service_user') THEN
    RAISE EXCEPTION 'Falta el rol pedidos_service_user: ejecuta antes 007_service_db_roles.sql (como postgres)';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS order_statuses (
    status_id smallint PRIMARY KEY,
    name varchar(30) NOT NULL,
    CONSTRAINT uq_order_statuses_name UNIQUE (name),
    CONSTRAINT ck_order_statuses_name_not_blank CHECK (btrim(name) <> '')
);

INSERT INTO order_statuses (status_id, name) VALUES
    (1, 'pendiente'), (2, 'pagado'), (3, 'enviado'), (4, 'cancelado')
ON CONFLICT (status_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS orders (
    order_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL,
    status_id smallint NOT NULL DEFAULT 1,
    total numeric(12, 2) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users (user_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_orders_status FOREIGN KEY (status_id) REFERENCES order_statuses (status_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_orders_total_nonnegative CHECK (total >= 0)
);
CREATE INDEX IF NOT EXISTS ix_orders_user_id ON orders (user_id);
CREATE INDEX IF NOT EXISTS ix_orders_status_id ON orders (status_id);

CREATE TABLE IF NOT EXISTS order_items (
    order_id bigint NOT NULL,
    book_id bigint NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(12, 2) NOT NULL,
    PRIMARY KEY (order_id, book_id),
    CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders (order_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_order_items_book FOREIGN KEY (book_id) REFERENCES books (book_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_order_items_quantity_positive CHECK (quantity > 0),
    CONSTRAINT ck_order_items_unit_price_nonnegative CHECK (unit_price >= 0)
);
CREATE INDEX IF NOT EXISTS ix_order_items_book_id ON order_items (book_id);

-- Función propia (no depende de trg_set_updated_at del monolito, que no existe en schema.sql).
CREATE OR REPLACE FUNCTION trg_orders_set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_orders_set_updated_at ON orders;
CREATE TRIGGER trg_orders_set_updated_at
    BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION trg_orders_set_updated_at();

-- ----------------------------------------------------------------------
-- Pedido completo (cabecera + líneas) como jsonb.
-- ----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_pedido_json(p_order_id bigint)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT jsonb_build_object(
               'order_id', o.order_id, 'user_id', o.user_id, 'status_id', o.status_id, 'status', s.name,
               'total', o.total, 'created_at', o.created_at, 'updated_at', o.updated_at,
               'items', coalesce((
                   SELECT jsonb_agg(jsonb_build_object('isbn', b.isbn, 'title', b.title,
                                                       'quantity', i.quantity, 'unit_price', i.unit_price)
                                    ORDER BY b.title)
                     FROM order_items i JOIN books b ON b.book_id = i.book_id
                    WHERE i.order_id = o.order_id), '[]'::jsonb))
      FROM orders o JOIN order_statuses s ON s.status_id = o.status_id
     WHERE o.order_id = p_order_id;
$$;

-- ----------------------------------------------------------------------
-- Crear pedido. p_items = [{"isbn": "...", "quantity": 2}, ...]  (isbn repetido se suma)
-- ----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_pedidos_crear(p_user_id bigint, p_items jsonb)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_el jsonb;
    v_lines jsonb;
    v_missing text;
    v_order_id bigint;
    v_total numeric(12, 2) := 0;
    r record;
BEGIN
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'El pedido necesita al menos una línea' USING ERRCODE = 'PD001';
    END IF;
    IF jsonb_array_length(p_items) > 100 THEN
        RAISE EXCEPTION 'Un pedido admite como máximo 100 líneas' USING ERRCODE = 'PD001';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = p_user_id AND is_active) THEN
        RAISE EXCEPTION 'El usuario no existe o está desactivado' USING ERRCODE = 'PD007';
    END IF;

    FOR v_el IN SELECT value FROM jsonb_array_elements(p_items) LOOP
        IF jsonb_typeof(v_el) <> 'object'
           OR coalesce(btrim(v_el->>'isbn'), '') = ''
           OR jsonb_typeof(v_el->'quantity') <> 'number'
           OR (v_el->>'quantity') !~ '^[1-9][0-9]{0,5}$' THEN
            RAISE EXCEPTION 'Cada línea necesita isbn y quantity entero entre 1 y 999999' USING ERRCODE = 'PD001';
        END IF;
    END LOOP;

    SELECT jsonb_agg(jsonb_build_object('isbn', t.isbn, 'qty', t.qty)) INTO v_lines
      FROM (SELECT btrim(value->>'isbn') AS isbn, sum((value->>'quantity')::integer) AS qty
              FROM jsonb_array_elements(p_items) GROUP BY 1) t;

    SELECT string_agg(l.isbn, ', ') INTO v_missing
      FROM jsonb_to_recordset(v_lines) AS l(isbn text, qty integer)
      LEFT JOIN books b ON b.isbn = l.isbn
     WHERE b.book_id IS NULL;
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'No existe(n) libro(s) con ISBN: %', v_missing USING ERRCODE = 'PD005';
    END IF;

    INSERT INTO orders (user_id) VALUES (p_user_id) RETURNING order_id INTO v_order_id;

    FOR r IN SELECT b.book_id, b.title, b.price, b.stock, l.qty
               FROM jsonb_to_recordset(v_lines) AS l(isbn text, qty integer)
               JOIN books b ON b.isbn = l.isbn
              ORDER BY b.book_id
                FOR UPDATE OF b LOOP
        IF r.stock < r.qty THEN
            RAISE EXCEPTION 'Stock insuficiente para "%" (disponible: %, solicitado: %)', r.title, r.stock, r.qty
                USING ERRCODE = 'PD002';
        END IF;
        UPDATE books SET stock = stock - r.qty WHERE book_id = r.book_id;
        INSERT INTO order_items (order_id, book_id, quantity, unit_price) VALUES (v_order_id, r.book_id, r.qty, r.price);
        v_total := v_total + r.price * r.qty;
    END LOOP;

    UPDATE orders SET total = v_total WHERE order_id = v_order_id;
    RETURN fn_pedido_json(v_order_id);
END $$;

-- ----------------------------------------------------------------------
-- Listado y detalle. p_user_id / p_actor_user_id NULL = sin restricción de dueño.
-- ----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_pedidos_listar(
    p_user_id bigint, p_status_id smallint, p_limit integer DEFAULT 50, p_offset integer DEFAULT 0)
RETURNS TABLE (order_id bigint, user_id bigint, status_id smallint, status varchar, total numeric,
               items_count bigint, created_at timestamptz, updated_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT o.order_id, o.user_id, o.status_id, s.name, o.total,
           (SELECT count(*) FROM order_items i WHERE i.order_id = o.order_id),
           o.created_at, o.updated_at
      FROM orders o JOIN order_statuses s ON s.status_id = o.status_id
     WHERE (p_user_id IS NULL OR o.user_id = p_user_id)
       AND (p_status_id IS NULL OR o.status_id = p_status_id)
     ORDER BY o.order_id DESC
     LIMIT greatest(least(coalesce(p_limit, 50), 200), 1)
    OFFSET greatest(coalesce(p_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION fn_pedido_obtener(p_order_id bigint, p_actor_user_id bigint)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v jsonb := fn_pedido_json(p_order_id);
BEGIN
    IF v IS NULL OR (p_actor_user_id IS NOT NULL AND (v->>'user_id')::bigint <> p_actor_user_id) THEN
        RAISE EXCEPTION 'No existe el pedido %', p_order_id USING ERRCODE = 'PD003';
    END IF;
    RETURN v;
END $$;

-- ----------------------------------------------------------------------
-- Cambio de estado: pendiente -> cancelado (repone stock) y pagado -> enviado.
-- (pendiente -> pagado solo lo hace fn_pagos_registrar.)
-- ----------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_pedido_cambiar_estado(p_order_id bigint, p_new_status_id smallint, p_actor_user_id bigint)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_order orders%ROWTYPE;
    v_old_name text;
    v_new_name text;
BEGIN
    SELECT * INTO v_order FROM orders WHERE order_id = p_order_id FOR UPDATE;
    IF NOT FOUND OR (p_actor_user_id IS NOT NULL AND v_order.user_id <> p_actor_user_id) THEN
        RAISE EXCEPTION 'No existe el pedido %', p_order_id USING ERRCODE = 'PD003';
    END IF;
    SELECT name INTO v_new_name FROM order_statuses WHERE status_id = p_new_status_id;
    IF v_new_name IS NULL THEN
        RAISE EXCEPTION 'Estado inválido: %', p_new_status_id USING ERRCODE = 'PD001';
    END IF;
    SELECT name INTO v_old_name FROM order_statuses WHERE status_id = v_order.status_id;
    IF NOT ((v_order.status_id = 1 AND p_new_status_id = 4) OR (v_order.status_id = 2 AND p_new_status_id = 3)) THEN
        RAISE EXCEPTION 'Transición no permitida: % -> %', v_old_name, v_new_name USING ERRCODE = 'PD004';
    END IF;

    IF p_new_status_id = 4 THEN
        PERFORM 1 FROM books
         WHERE book_id IN (SELECT book_id FROM order_items WHERE order_id = p_order_id)
         ORDER BY book_id FOR UPDATE;
        UPDATE books b SET stock = b.stock + i.quantity
          FROM order_items i WHERE i.order_id = p_order_id AND i.book_id = b.book_id;
    END IF;
    UPDATE orders SET status_id = p_new_status_id WHERE order_id = p_order_id;
    RETURN fn_pedido_json(p_order_id);
END $$;

-- ============================ PERMISOS ===============================
DO $$
DECLARE
    r record;
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO pedidos_service_user', current_database());
    GRANT USAGE ON SCHEMA public TO pedidos_service_user;
    FOR r IN SELECT p.oid::regprocedure AS sig
               FROM pg_proc p
              WHERE p.pronamespace = 'public'::regnamespace AND p.proname LIKE 'fn\_pedido%' LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', r.sig);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO pedidos_service_user', r.sig);
    END LOOP;
END $$;

COMMIT;
