-- Deshace 008 (funciones de Users y Authors). Ejecutar como library_user, DESPUÉS de 993.
-- No toca datos: solo elimina las funciones fn_users_* y fn_authors_*.
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT p.oid::regprocedure AS sig
               FROM pg_proc p
              WHERE p.pronamespace = 'public'::regnamespace
                AND (p.proname LIKE 'fn\_users\_%' OR p.proname LIKE 'fn\_authors\_%') LOOP
        EXECUTE format('DROP FUNCTION IF EXISTS %s', r.sig);
    END LOOP;
END $$;

COMMIT;
