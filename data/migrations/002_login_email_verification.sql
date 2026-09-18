-- =====================================================================
-- 002 · Servicio login: confirmación del correo (envío por Postfix)
-- ---------------------------------------------------------------------
-- Requiere 001. ADITIVA E IDEMPOTENTE, una sola transacción.
--   * users.email_verified_at: NULL = correo sin confirmar.
--       DEFAULT CURRENT_TIMESTAMP => las cuentas que YA existen (administrador y
--       usuarios del monolito) y las que el monolito cree después quedan como
--       verificadas: las creó un administrador, no un registro público. Solo el
--       servicio login inserta NULL explícito en los registros públicos.
--       Es un "fast default" (PostgreSQL 11+): no reescribe la tabla ni toma
--       el candado por mucho tiempo, y NO ejecuta ningún UPDATE.
--   * email_verifications: tokens de confirmación (solo se guarda su SHA-256).
--   * No se altera ninguna columna/constraint/vista/función existente.
--
-- Ejecutar como el DUEÑO de las tablas (library_user):
--   PGPASSWORD=... psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/002_login_email_verification.sql
-- =====================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at timestamptz DEFAULT CURRENT_TIMESTAMP;

CREATE TABLE IF NOT EXISTS email_verifications (
    verification_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL,
    token_hash char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    CONSTRAINT uq_email_verifications_token UNIQUE (token_hash),
    CONSTRAINT fk_email_verifications_user FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT ck_email_verifications_hash CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_email_verifications_expiry CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS ix_email_verifications_user_id ON email_verifications (user_id);

COMMIT;
