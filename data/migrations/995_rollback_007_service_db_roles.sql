-- Deshace 007: elimina los roles de BD de Users, Authors, Pedidos y Pagos.
-- Ejecutar como superusuario (postgres), DESPUÉS de 994 (ya no deben quedar sus funciones/permisos).
--   sudo -u postgres psql -d library_db -f data/migrations/995_rollback_007_service_db_roles.sql
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['users_service_user', 'authors_service_user', 'pedidos_service_user', 'pagos_service_user'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('DROP OWNED BY %I', v_role);   -- quita sus permisos
            EXECUTE format('DROP ROLE %I', v_role);
        END IF;
    END LOOP;
END $$;
