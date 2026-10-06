-- =====================================================================
-- 011 · Quita EXECUTE a PUBLIC de las funciones de books/SOAP ya existentes
-- ---------------------------------------------------------------------
-- PostgreSQL concede EXECUTE a PUBLIC al crear una función. Las funciones SECURITY DEFINER de
-- books (fn_crear_libro, fn_actualizar_libro, fn_eliminar_libro...) nacieron así, por lo que
-- CUALQUIER rol con acceso a la base (login_service_user y los 4 roles nuevos de Users,
-- Authors, Pedidos y Pagos) podía llamarlas y, por ejemplo, borrar libros saltándose el JWT
-- y los roles del servicio books. Comprobado con una llamada real a fn_eliminar_libro.
--
-- Esta migración solo REVOCA a PUBLIC y deja el permiso EXPLÍCITO para soap_service_user (el rol
-- del servicio books). No cambia datos ni definiciones. Idempotente.
-- Ejecutar como POSTGRES (superusuario), después de 006-010: las funciones de sql/soap_module.sql
-- las creó el superusuario que lo aplicó, y solo su dueño o un superusuario puede revocarlas
-- (como library_user daría "no privileges could be revoked" en ésas).
--   sudo -u postgres psql -d library_db -v ON_ERROR_STOP=1 -f data/migrations/011_revoke_public_execute_books_functions.sql
-- =====================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT p.oid::regprocedure AS sig
               FROM pg_proc p
              WHERE p.pronamespace = 'public'::regnamespace
                AND p.proname IN ('fn_registrar_peticion_cliente', 'fn_conceptos_pendientes',
                                  'fn_registrar_clasificacion', 'fn_progreso_usuario',
                                  'fn_libros_con_imagenes', 'fn_listar_libros',
                                  'fn_crear_libro', 'fn_actualizar_libro', 'fn_eliminar_libro') LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', r.sig);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'soap_service_user') THEN
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO soap_service_user', r.sig);
        END IF;
    END LOOP;
END $$;

COMMIT;
