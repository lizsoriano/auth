-- 003 · Mínimo privilegio para el rol login_service_user (idempotente, COMPLETO).
-- Reemplaza al antiguo 002_login_service_grants.sql: se ejecuta al final, después de 001 y 002.
-- Requiere 000_create_login_role.sql. Ejecutar como dueño (library_user).
--
-- Garantías:
--   * INSERT solo en columnas concretas de users: el servicio NO puede crear
--     administradores (is_admin queda en su default false) ni tocar is_active/updated_at.
--   * Su único UPDATE sobre users es email_verified_at (confirmar el correo).
--   * Sin DELETE en ninguna tabla. Sin ningún permiso sobre books/catálogo.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'login_service_user') THEN
    RAISE EXCEPTION 'El rol login_service_user no existe: ejecuta antes 000_create_login_role.sql';
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO login_service_user', current_database());
END $$;

GRANT USAGE ON SCHEMA public TO login_service_user;

GRANT SELECT (user_id, email, password_hash, display_name, nombre, apellido_paterno,
              apellido_materno, is_active, created_at, email_verified_at) ON users TO login_service_user;
GRANT INSERT (email, password_hash, display_name, nombre, apellido_paterno, apellido_materno,
              email_verified_at) ON users TO login_service_user;
GRANT UPDATE (email_verified_at) ON users TO login_service_user;

GRANT SELECT, INSERT ON login_sessions TO login_service_user;
GRANT UPDATE (revoked_at) ON login_sessions TO login_service_user;

GRANT SELECT, INSERT ON email_verifications TO login_service_user;
GRANT UPDATE (used_at) ON email_verifications TO login_service_user;
