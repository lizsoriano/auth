-- ROLLBACK de 001. DESTRUCTIVO: borra sesiones y los nombres/apellidos guardados
-- en users por el servicio login. No elimina usuarios ni toca books/catálogo.
--   psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/999_rollback_001_login_service.sql
--
-- Antes: detén el servicio login y ejecuta 998 (si aplicaste 002). Las cuentas registradas por él seguirán existiendo en
-- users con su display_name y password_hash bcrypt (el monolito puede seguir usándolas).
BEGIN;
SET LOCAL lock_timeout = '5s';
DROP TABLE IF EXISTS login_sessions;
DROP INDEX IF EXISTS uq_users_email_lower;
ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_person_name;
ALTER TABLE users DROP COLUMN IF EXISTS nombre;
ALTER TABLE users DROP COLUMN IF EXISTS apellido_paterno;
ALTER TABLE users DROP COLUMN IF EXISTS apellido_materno;
COMMIT;
-- El rol no se elimina aquí. Si ya no hace falta (como superusuario):
--   REVOKE ALL ON ALL TABLES IN SCHEMA public FROM login_service_user;
--   REVOKE ALL ON SCHEMA public FROM login_service_user;
--   REVOKE ALL ON DATABASE library_db FROM login_service_user;
--   DROP ROLE login_service_user;
