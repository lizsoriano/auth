-- =====================================================================
-- Verificación funcional de las migraciones 006-011 (roles, Users, Authors, Pedidos, Pagos).
-- Solo lectura efectiva: TODO corre dentro de una transacción que termina en ROLLBACK.
--
-- Requiere una base con el esquema, books/SOAP y 006-011 aplicadas, y datos de prueba:
-- 3 libros (stock 20, 12 y 5), 3 autores, y 3 usuarios (id 1 = administrador del monolito con
-- is_admin = true; 2 y 3 = cuentas normales). Ver data/README.md, sección "Cómo se verificó".
--
--   docker exec -i <contenedor> psql -U postgres -d library_db -f - < data/tests/verify_microservices_db.sql
-- Cada comprobación imprime "ok - ..."; si algo falla, aborta con "FALLÓ: ...".
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

CREATE FUNCTION pg_temp.ok(p_cond boolean, p_msg text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    IF p_cond IS NOT TRUE THEN RAISE EXCEPTION 'FALLÓ: %', p_msg; END IF;
    RAISE NOTICE 'ok  - %', p_msg;
END $$;

CREATE FUNCTION pg_temp.expect_err(p_sql text, p_code text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_state text;
    v_failed boolean := false;
BEGIN
    BEGIN
        EXECUTE p_sql;
    EXCEPTION WHEN OTHERS THEN
        v_failed := true;
        v_state := SQLSTATE;
    END;
    IF NOT v_failed THEN RAISE EXCEPTION 'FALLÓ: esperaba el error % y no falló: %', p_code, p_sql; END IF;
    IF v_state <> p_code THEN RAISE EXCEPTION 'FALLÓ: esperaba % pero fue %: %', p_code, v_state, p_sql; END IF;
    RAISE NOTICE 'ok  - error % esperado: %', p_code, left(p_sql, 70);
END $$;

-- ============================ ROLES / USERS ==========================
DO $$
DECLARE
    v_id bigint;
    v_admin2 bigint;
BEGIN
    PERFORM pg_temp.ok((SELECT role_id FROM users WHERE user_id = 1) = 1, 'el administrador del monolito quedó como role admin (1)');
    PERFORM pg_temp.ok((SELECT count(*) FROM users WHERE role_id = 3) = 2, 'las otras dos cuentas son customer (3)');

    UPDATE users SET is_admin = false WHERE user_id = 1;
    PERFORM pg_temp.ok((SELECT role_id FROM users WHERE user_id = 1) = 1, 'quitar is_admin no baja el role_id');
    UPDATE users SET is_admin = true WHERE user_id = 3;
    PERFORM pg_temp.ok((SELECT role_id FROM users WHERE user_id = 3) = 1, 'el monolito promueve (is_admin) => role admin por trigger');
    UPDATE users SET is_admin = false, role_id = 3 WHERE user_id = 3;
    UPDATE users SET is_admin = true WHERE user_id = 1;

    v_id := fn_users_create('  Nuevo@X.com ', '$2b$12$hash', ' Nuevo ', NULL, NULL, NULL, NULL);
    PERFORM pg_temp.ok((SELECT email FROM users WHERE user_id = v_id) = 'nuevo@x.com', 'fn_users_create normaliza el correo a minúsculas');
    PERFORM pg_temp.ok((SELECT role_id = 3 AND email_verified_at IS NOT NULL AND NOT is_admin FROM users WHERE user_id = v_id),
                       'alta por administrador: customer, correo verificado, is_admin = false');
    PERFORM pg_temp.expect_err($q$select fn_users_create('NUEVO@x.com','h','dup',NULL,NULL,NULL,NULL)$q$, '23505');
    PERFORM pg_temp.expect_err($q$select fn_users_create('r@x.com','h','R',NULL,NULL,NULL,9::smallint)$q$, '23503');
    PERFORM pg_temp.expect_err($q$select fn_users_create('p@x.com','h','P','Solo',NULL,NULL,NULL)$q$, '23514');

    PERFORM pg_temp.ok((SELECT count(*) FROM fn_users_list(100, 0)) = 4, 'fn_users_list devuelve los 4 usuarios');
    PERFORM pg_temp.ok((SELECT role_name FROM fn_users_get(1)) = 'admin', 'fn_users_get trae el nombre del rol');
    PERFORM pg_temp.ok(NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'fn_users_list' AND column_name = 'password_hash'), 'el listado no expone password_hash');

    PERFORM pg_temp.expect_err('select fn_users_update(999,NULL,NULL,NULL,NULL,NULL,NULL,NULL)', 'US001');
    PERFORM pg_temp.expect_err('select fn_users_update(1,NULL,NULL,NULL,NULL,NULL,3::smallint,NULL)', 'US002');
    PERFORM pg_temp.expect_err('select fn_users_update(1,NULL,NULL,NULL,NULL,NULL,NULL,false)', 'US002');
    PERFORM pg_temp.expect_err('select fn_users_delete(1)', 'US002');
    v_admin2 := fn_users_create('admin2@x.com', 'h', 'Admin2', NULL, NULL, NULL, 1::smallint);
    PERFORM fn_users_update(1, NULL, NULL, NULL, NULL, NULL, 3::smallint, NULL);
    PERFORM pg_temp.ok((SELECT role_id FROM users WHERE user_id = 1) = 3, 'con otro admin activo sí se puede bajar el rol');

    PERFORM fn_users_update(v_id, 'Cambio@X.com', 'Nuevo Nombre', 'N', 'AP', 'AM', 2::smallint, false);
    PERFORM pg_temp.ok((SELECT email = 'cambio@x.com' AND role_id = 2 AND NOT is_active AND nombre = 'N' FROM users WHERE user_id = v_id),
                       'fn_users_update (PATCH) cambia correo, rol, estado y nombre');
    PERFORM fn_users_update(v_id, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
    PERFORM pg_temp.ok((SELECT email FROM users WHERE user_id = v_id) = 'cambio@x.com', 'NULL conserva el valor actual');

    PERFORM fn_users_set_password(v_id, '$2b$12$otro');
    PERFORM pg_temp.ok(fn_users_get_password_hash(v_id) = '$2b$12$otro', 'fn_users_set_password / get_password_hash');
    PERFORM pg_temp.expect_err('select fn_users_set_password(999, ''x'')', 'US001');

    PERFORM pg_temp.expect_err('select fn_users_delete(' || v_admin2 || ')', 'US002');   -- ya es el único admin
    PERFORM fn_users_update(1, NULL, NULL, NULL, NULL, NULL, 1::smallint, NULL);
    PERFORM fn_users_delete(v_admin2);
    PERFORM pg_temp.ok(NOT EXISTS (SELECT 1 FROM users WHERE user_id = v_admin2), 'con otro admin activo fn_users_delete sí borra al usuario');
END $$;

-- ============================ AUTHORS ================================
DO $$
DECLARE
    v_id bigint;
BEGIN
    v_id := fn_authors_create(' Isaac ', ' ', 'Bio');
    PERFORM pg_temp.ok((SELECT first_name = 'Isaac' AND last_name IS NULL FROM authors WHERE author_id = v_id), 'fn_authors_create recorta y deja last_name NULL si viene vacío');
    PERFORM pg_temp.ok((SELECT count(*) FROM fn_authors_list(100, 0)) = 4, 'fn_authors_list');
    PERFORM pg_temp.ok((SELECT books_count FROM fn_authors_get(1)) = 1, 'fn_authors_get cuenta sus libros');

    PERFORM fn_authors_update(v_id, 'Isaac', 'Asimov', NULL, false);
    PERFORM pg_temp.ok((SELECT last_name = 'Asimov' AND biography = 'Bio' FROM authors WHERE author_id = v_id), 'PATCH conserva lo que no se manda');
    PERFORM fn_authors_update(v_id, 'Isaac', NULL, 'Nueva', true);
    PERFORM pg_temp.ok((SELECT last_name IS NULL AND biography = 'Nueva' FROM authors WHERE author_id = v_id), 'PUT reemplaza todo (last_name vuelve a NULL)');
    PERFORM pg_temp.expect_err('select fn_authors_update(999, ''a'', ''b'', ''c'', true)', 'AU001');

    PERFORM fn_authors_link_book(v_id, '9780000000006', NULL);
    PERFORM pg_temp.ok((SELECT author_order FROM book_authors WHERE author_id = v_id AND book_id = 1) = 2, 'link_book asigna el siguiente author_order');
    PERFORM pg_temp.ok((SELECT authors FROM fn_listar_libros() WHERE isbn = '9780000000006') = 'George Orwell, Isaac',
                       'books refleja el nuevo autor (por eso Authors invalida la caché books:*)');
    PERFORM pg_temp.expect_err('select fn_authors_link_book(' || v_id || ', ''9780000000006'', NULL)', 'AU003');
    PERFORM pg_temp.expect_err('select fn_authors_link_book(' || v_id || ', ''0000000000'', NULL)', 'AU002');
    PERFORM pg_temp.expect_err('select fn_authors_link_book(999, ''9780000000006'', NULL)', 'AU001');
    PERFORM pg_temp.expect_err('select fn_authors_delete(' || v_id || ')', '23503');
    PERFORM fn_authors_unlink_book(v_id, '9780000000006');
    PERFORM pg_temp.expect_err('select fn_authors_unlink_book(' || v_id || ', ''9780000000006'')', 'AU004');
    PERFORM fn_authors_delete(v_id);
    PERFORM pg_temp.ok(NOT EXISTS (SELECT 1 FROM authors WHERE author_id = v_id), 'fn_authors_delete borra al autor sin libros');
END $$;

-- ====================== PEDIDOS (stock transaccional) ================
DO $$
DECLARE
    v jsonb;
    v_order bigint;
BEGIN
    v := fn_pedidos_crear(2, '[{"isbn":"9780000000006","quantity":2},{"isbn":"9780000000006","quantity":1},{"isbn":"9780000000001","quantity":1}]');
    v_order := (v->>'order_id')::bigint;
    PERFORM pg_temp.ok((v->>'total')::numeric = 1006.00, 'total = 3 x 219 + 1 x 349 (isbn repetido se suma)');
    PERFORM pg_temp.ok(v->>'status' = 'pendiente' AND jsonb_array_length(v->'items') = 2, 'nace pendiente con 2 líneas');
    PERFORM pg_temp.ok((SELECT stock FROM books WHERE book_id = 1) = 17 AND (SELECT stock FROM books WHERE book_id = 2) = 11, 'el stock bajó (20->17, 12->11)');

    PERFORM pg_temp.expect_err($q$select fn_pedidos_crear(2, '[{"isbn":"9780000000030","quantity":6}]')$q$, 'PD002');
    PERFORM pg_temp.ok((SELECT stock FROM books WHERE book_id = 3) = 5, 'un pedido rechazado por stock no deja nada descontado');
    PERFORM pg_temp.ok((SELECT count(*) FROM orders) = 1, 'ni deja un pedido a medias');
    PERFORM pg_temp.expect_err($q$select fn_pedidos_crear(2, '[{"isbn":"0000","quantity":1}]')$q$, 'PD005');
    PERFORM pg_temp.expect_err($q$select fn_pedidos_crear(2, '[]')$q$, 'PD001');
    PERFORM pg_temp.expect_err($q$select fn_pedidos_crear(2, '[{"isbn":"9780000000006","quantity":0}]')$q$, 'PD001');
    PERFORM pg_temp.expect_err($q$select fn_pedidos_crear(2, '[{"isbn":"9780000000006","quantity":"2"}]')$q$, 'PD001');
    PERFORM pg_temp.expect_err($q$select fn_pedidos_crear(2, '[{"isbn":"9780000000006","quantity":1.5}]')$q$, 'PD001');
    PERFORM pg_temp.expect_err($q$select fn_pedidos_crear(999, '[{"isbn":"9780000000006","quantity":1}]')$q$, 'PD007');

    PERFORM pg_temp.ok((SELECT count(*) FROM fn_pedidos_listar(2, NULL, 50, 0)) = 1, 'el cliente 2 ve su pedido');
    PERFORM pg_temp.ok((SELECT count(*) FROM fn_pedidos_listar(3, NULL, 50, 0)) = 0, 'el cliente 3 no ve pedidos ajenos');
    PERFORM pg_temp.ok((SELECT count(*) FROM fn_pedidos_listar(NULL, 1::smallint, 50, 0)) = 1, 'staff/admin (NULL) filtran por estado');
    PERFORM pg_temp.ok((fn_pedido_obtener(v_order, 2)->>'order_id')::bigint = v_order, 'el dueño obtiene su pedido');
    PERFORM pg_temp.expect_err('select fn_pedido_obtener(' || v_order || ', 3)', 'PD003');
    PERFORM pg_temp.ok(fn_pedido_obtener(v_order, NULL) IS NOT NULL, 'admin/staff (NULL) obtienen cualquiera');

    PERFORM pg_temp.expect_err('select fn_pedido_cambiar_estado(' || v_order || ', 3::smallint, NULL)', 'PD004');
    PERFORM pg_temp.expect_err('select fn_pedido_cambiar_estado(' || v_order || ', 9::smallint, NULL)', 'PD001');
    PERFORM pg_temp.expect_err('select fn_pedido_cambiar_estado(' || v_order || ', 4::smallint, 3)', 'PD003');
    v := fn_pedido_cambiar_estado(v_order, 4::smallint, 2);
    PERFORM pg_temp.ok(v->>'status' = 'cancelado', 'el dueño cancela su pedido pendiente');
    PERFORM pg_temp.ok((SELECT stock FROM books WHERE book_id = 1) = 20 AND (SELECT stock FROM books WHERE book_id = 2) = 12, 'cancelar repone el stock (vuelve a 20 y 12)');
    PERFORM pg_temp.expect_err('select fn_pedido_cambiar_estado(' || v_order || ', 4::smallint, NULL)', 'PD004');
END $$;

-- ====================== PAGOS (atómico + idempotente) ================
DO $$
DECLARE
    v jsonb;
    v1 bigint;
    v2 bigint;
    v_pay bigint;
BEGIN
    v1 := (fn_pedidos_crear(2, '[{"isbn":"9780000000006","quantity":1}]')->>'order_id')::bigint;   -- total 219
    v2 := (fn_pedidos_crear(3, '[{"isbn":"9780000000001","quantity":1}]')->>'order_id')::bigint;   -- total 349

    PERFORM pg_temp.expect_err('select fn_pagos_registrar(' || v1 || ', 2, false, ''tarjeta'', 100, ''k1'')', 'PG003');
    PERFORM pg_temp.expect_err('select fn_pagos_registrar(' || v1 || ', 3, false, ''tarjeta'', 219, ''k1'')', 'PG001');
    PERFORM pg_temp.expect_err('select fn_pagos_registrar(' || v1 || ', 2, false, ''bitcoin'', 219, ''k1'')', 'PG005');
    PERFORM pg_temp.expect_err('select fn_pagos_registrar(' || v1 || ', 2, false, ''tarjeta'', 219, '' '')', 'PG005');
    PERFORM pg_temp.expect_err('select fn_pagos_registrar(999, 2, false, ''tarjeta'', 219, ''k1'')', 'PG001');
    PERFORM pg_temp.ok((SELECT status_id FROM orders WHERE order_id = v1) = 1, 'los intentos fallidos no cambian el pedido');

    v := fn_pagos_registrar(v1, 2, false, 'tarjeta', 219, 'k1');
    v_pay := (v->>'payment_id')::bigint;
    PERFORM pg_temp.ok(v->>'order_status' = 'pagado' AND (v->>'duplicated')::boolean = false, 'pago registrado: el pedido pasa a pagado');
    PERFORM pg_temp.ok((SELECT status_id FROM orders WHERE order_id = v1) = 2, 'el estado del pedido se actualizó en la misma transacción');

    v := fn_pagos_registrar(v1, 2, false, 'tarjeta', 219, 'k1');
    PERFORM pg_temp.ok((v->>'duplicated')::boolean AND (v->>'payment_id')::bigint = v_pay, 'misma clave + mismo pedido => devuelve el pago original (no cobra dos veces)');
    PERFORM pg_temp.ok((SELECT count(*) FROM payments WHERE order_id = v1) = 1, 'sigue habiendo un solo pago');
    PERFORM pg_temp.expect_err('select fn_pagos_registrar(' || v2 || ', 3, false, ''tarjeta'', 349, ''k1'')', 'PG004');
    PERFORM pg_temp.expect_err('select fn_pagos_registrar(' || v1 || ', 2, false, ''tarjeta'', 219, ''k-otra'')', 'PG002');

    PERFORM pg_temp.ok((fn_pagos_registrar(v2, 1, true, 'efectivo', 349, 'k2')->>'order_status') = 'pagado', 'admin/staff pueden pagar un pedido ajeno');
    PERFORM pg_temp.ok((SELECT count(*) FROM fn_pagos_listar(2, NULL, 50, 0)) = 1 AND (SELECT count(*) FROM fn_pagos_listar(NULL, NULL, 50, 0)) = 2,
                       'el cliente ve sus pagos; admin/staff ven todos');
    PERFORM pg_temp.ok(fn_pago_obtener(v_pay, 2) IS NOT NULL, 'el dueño obtiene su pago');
    PERFORM pg_temp.expect_err('select fn_pago_obtener(' || v_pay || ', 3)', 'PG006');

    PERFORM pg_temp.expect_err('select fn_pedido_cambiar_estado(' || v1 || ', 4::smallint, NULL)', 'PD004');
    PERFORM pg_temp.ok((fn_pedido_cambiar_estado(v1, 3::smallint, NULL)->>'status') = 'enviado', 'un pedido pagado se puede enviar');
END $$;

ROLLBACK;
