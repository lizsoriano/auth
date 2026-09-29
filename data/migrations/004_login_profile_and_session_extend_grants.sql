-- 004 · Permisos adicionales para PATCH /profile y POST /session/extend.
-- Aditivo: solo agrega UPDATE sobre columnas concretas al rol ya existente
-- (login_service_user). No crea tablas ni cambia datos.
-- Ejecutar como library_user (dueño), después de 001-003.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'login_service_user') THEN
    RAISE EXCEPTION 'El rol login_service_user no existe: ejecuta antes 000_create_login_role.sql';
  END IF;
END $$;

GRANT UPDATE (nombre, apellido_paterno, apellido_materno, display_name, email, password_hash)
    ON users TO login_service_user;
GRANT UPDATE (expires_at) ON login_sessions TO login_service_user;
