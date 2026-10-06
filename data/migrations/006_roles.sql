-- =====================================================================
-- 006 · Roles de aplicación (admin / staff / customer) y users.role_id
-- ---------------------------------------------------------------------
-- El JWT que emite login lleva `user_id` y `role_id`; las operaciones
-- administrativas de todos los microservicios comparan ese role_id.
--
-- ADITIVA E IDEMPOTENTE:
--   * tabla nueva `roles` (1 admin, 2 staff, 3 customer);
--   * users.role_id smallint NOT NULL DEFAULT 3 (customer) con FK a roles.
--     Es un "fast default" (PostgreSQL 11+): no reescribe la tabla.
--   * El monolito y el registro público de login insertan sin role_id =>
--     nacen `customer`. Nadie puede auto-asignarse un rol mayor.
--   * Único UPDATE sobre filas existentes: el administrador del monolito
--     (is_admin = true) pasa a role_id = 1. Es idempotente.
--   * Trigger: si el monolito crea/promueve a alguien con is_admin = true,
--     su role_id pasa a 1. Solo se dispara al tocar is_admin; cambiar
--     role_id desde el servicio Users NO lo dispara.
--   * `is_admin` y el índice único de un solo administrador (monolito) NO
--     se tocan: los roles de los servicios son independientes de ese flag.
--
-- Ejecutar como library_user (dueño), después de 001-005:
--   PGPASSWORD=... psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/006_roles.sql
-- =====================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS roles (
    role_id smallint PRIMARY KEY,
    name varchar(30) NOT NULL,
    description text,
    CONSTRAINT uq_roles_name UNIQUE (name),
    CONSTRAINT ck_roles_name_not_blank CHECK (btrim(name) <> '')
);

INSERT INTO roles (role_id, name, description) VALUES
    (1, 'admin',    'Administra usuarios, roles, autores, libros, pedidos y pagos'),
    (2, 'staff',    'Gestiona catálogo, pedidos y pagos; no administra usuarios'),
    (3, 'customer', 'Cliente: consulta el catálogo y gestiona solo sus propios pedidos y pagos')
ON CONFLICT (role_id) DO NOTHING;

ALTER TABLE users ADD COLUMN IF NOT EXISTS role_id smallint NOT NULL DEFAULT 3;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.users'::regclass AND conname = 'fk_users_role') THEN
    ALTER TABLE users ADD CONSTRAINT fk_users_role FOREIGN KEY (role_id)
        REFERENCES roles (role_id) ON UPDATE CASCADE ON DELETE RESTRICT;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_users_role_id ON users (role_id);

UPDATE users SET role_id = 1 WHERE is_admin AND role_id <> 1;

CREATE OR REPLACE FUNCTION trg_users_admin_role() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.is_admin AND NEW.role_id <> 1 THEN
        NEW.role_id := 1;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_users_admin_role ON users;
CREATE TRIGGER trg_users_admin_role
    BEFORE INSERT OR UPDATE OF is_admin ON users
    FOR EACH ROW EXECUTE FUNCTION trg_users_admin_role();

-- login lee el rol para ponerlo en el JWT. Sigue sin poder modificarlo.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'login_service_user') THEN
    GRANT SELECT (role_id) ON users TO login_service_user;
  END IF;
END $$;

COMMIT;
