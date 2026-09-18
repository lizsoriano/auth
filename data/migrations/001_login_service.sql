-- =====================================================================
-- 001 · Servicio login: nombre en columnas atómicas + sesiones
-- ---------------------------------------------------------------------
-- Para una BD YA EXISTENTE (books, Electron y monolito en marcha).
-- Equivale a lo que data/schema.sql ya incluye para instalaciones nuevas.
--
-- ADITIVA E IDEMPOTENTE:
--   * users: 3 columnas NULLABLE nuevas (sin default => solo metadatos, no
--     reescribe la tabla), 1 CHECK y 1 índice único sobre lower(email).
--     Ninguna columna/constraint existente se altera, renombra ni elimina.
--   * login_sessions: tabla nueva (nadie más la usa).
--   * No se toca books, catálogos, vistas, funciones ni permisos de otros roles.
--
-- Ejecutar como el DUEÑO de las tablas (library_user):
--   PGPASSWORD=... psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/001_login_service.sql
--
-- Si algo falla, TODO se revierte (una sola transacción).
-- =====================================================================
BEGIN;

-- ALTER TABLE pide un candado breve sobre users. Si la tabla está ocupada,
-- falla en 5 s en lugar de encolarse y bloquear al monolito.
SET LOCAL lock_timeout = '5s';

ALTER TABLE users ADD COLUMN IF NOT EXISTS nombre           varchar(120);
ALTER TABLE users ADD COLUMN IF NOT EXISTS apellido_paterno varchar(120);
ALTER TABLE users ADD COLUMN IF NOT EXISTS apellido_materno varchar(120);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conrelid = 'public.users'::regclass AND conname = 'ck_users_person_name') THEN
    -- Las filas actuales (todo NULL) cumplen la regla: o no hay nombre, o están los tres campos.
    ALTER TABLE users ADD CONSTRAINT ck_users_person_name CHECK (
        num_nulls(nombre, apellido_paterno, apellido_materno) IN (0, 3)
        AND coalesce(btrim(nombre), 'x') <> ''
        AND coalesce(btrim(apellido_paterno), 'x') <> ''
        AND coalesce(btrim(apellido_materno), 'x') <> ''
    );
  END IF;
END $$;

-- Falla (y revierte todo) si ya existieran correos duplicados salvo por mayúsculas.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (lower(email));

CREATE TABLE IF NOT EXISTS login_sessions (
    session_id uuid PRIMARY KEY,
    user_id bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    ip_address inet,
    user_agent varchar(400),
    CONSTRAINT fk_login_sessions_user FOREIGN KEY (user_id)
        REFERENCES users (user_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT ck_login_sessions_expiry CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS ix_login_sessions_user_id ON login_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_login_sessions_active_expiry ON login_sessions (expires_at) WHERE revoked_at IS NULL;

COMMIT;
