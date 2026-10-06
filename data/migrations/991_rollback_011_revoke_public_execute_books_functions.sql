-- Deshace 011: vuelve a conceder EXECUTE a PUBLIC en las funciones de books/SOAP (el estado anterior,
-- que permitía a cualquier rol de la base llamarlas). Ejecutar como postgres ANTES que 992.
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
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO PUBLIC', r.sig);
    END LOOP;
END $$;

COMMIT;
