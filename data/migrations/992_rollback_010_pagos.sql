-- Deshace 010 (Pagos). Ejecutar como library_user ANTES que 993.
-- Borra la tabla payments (se pierden los pagos registrados) y sus funciones.
-- Los pedidos que estaban en "pagado" se quedan en "pagado".
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT p.oid::regprocedure AS sig
               FROM pg_proc p
              WHERE p.pronamespace = 'public'::regnamespace AND p.proname LIKE 'fn\_pago%' LOOP
        EXECUTE format('DROP FUNCTION IF EXISTS %s', r.sig);
    END LOOP;
END $$;

DROP TABLE IF EXISTS payments;

COMMIT;
