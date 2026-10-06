-- Deshace 006 (roles). Ejecutar como library_user, DESPUÉS de 995 y ANTES de 998/999.
-- Quita users.role_id, el trigger y la tabla roles. NO borra ninguna fila de users
-- (el flag is_admin no se tocó nunca). Se pierden las asignaciones de rol hechas por Users.
BEGIN;
SET LOCAL lock_timeout = '5s';

DROP TRIGGER IF EXISTS trg_users_admin_role ON users;
DROP FUNCTION IF EXISTS trg_users_admin_role();
DROP INDEX IF EXISTS ix_users_role_id;
ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_role;
ALTER TABLE users DROP COLUMN IF EXISTS role_id;   -- los permisos por columna desaparecen con la columna
DROP TABLE IF EXISTS roles;

COMMIT;
