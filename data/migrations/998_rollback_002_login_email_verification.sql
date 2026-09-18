-- ROLLBACK de 002 (confirmación de correo). DESTRUCTIVO: borra los tokens de confirmación
-- y la marca de verificación. No elimina usuarios ni toca books/catálogo.
-- Ejecutar ANTES que 999 (que deshace 001). Detén primero el servicio login.
--   psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/998_rollback_002_login_email_verification.sql
BEGIN;
SET LOCAL lock_timeout = '5s';
DROP TABLE IF EXISTS email_verifications;
ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at;
COMMIT;
