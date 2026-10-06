-- Deshace 009 (Pedidos). Ejecutar como library_user, DESPUÉS de 992.
-- Devuelve a books.stock lo que reservaban los pedidos PENDIENTES (los pagados/enviados ya
-- salieron del inventario y NO se reponen). Luego borra order_items, orders, order_statuses y
-- las funciones. Se pierde el historial de pedidos.
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF to_regclass('public.payments') IS NOT NULL THEN
    RAISE EXCEPTION 'Existe la tabla payments: ejecuta antes 992_rollback_010_pagos.sql';
  END IF;
END $$;

UPDATE books b SET stock = b.stock + s.qty
  FROM (SELECT i.book_id, sum(i.quantity) AS qty
          FROM order_items i JOIN orders o ON o.order_id = i.order_id
         WHERE o.status_id = 1
         GROUP BY i.book_id) s
 WHERE s.book_id = b.book_id;

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT p.oid::regprocedure AS sig
               FROM pg_proc p
              WHERE p.pronamespace = 'public'::regnamespace AND p.proname LIKE 'fn\_pedido%' LOOP
        EXECUTE format('DROP FUNCTION IF EXISTS %s', r.sig);
    END LOOP;
END $$;

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;   -- se lleva el trigger trg_orders_set_updated_at
DROP TABLE IF EXISTS order_statuses;
DROP FUNCTION IF EXISTS trg_orders_set_updated_at();

COMMIT;
