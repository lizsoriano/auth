-- 005 · Permiso adicional para el claim "role" del JWT (POST /login).
-- Aditivo: agrega SOLO un SELECT sobre una columna existente (is_admin) al
-- rol ya existente (login_service_user). No crea tablas, no cambia datos,
-- no toca ningún otro permiso. login_service_user sigue sin poder
-- modificar is_admin (nunca se le otorgó UPDATE/INSERT sobre esa columna).
-- Ejecutar como library_user (dueño), después de 001-004.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'login_service_user') THEN
    RAISE EXCEPTION 'El rol login_service_user no existe: ejecuta antes 000_create_login_role.sql';
  END IF;
END $$;

GRANT SELECT (is_admin) ON users TO login_service_user;
