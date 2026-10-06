-- =====================================================================
-- 008 · Funciones de los microservicios Users y Authors
-- ---------------------------------------------------------------------
-- Mismo criterio de mínimo privilegio que books (ED-11): funciones
-- SECURITY DEFINER y SOLO EXECUTE para el rol del servicio. users_service_user
-- y authors_service_user no pueden leer ni escribir ninguna tabla directamente
-- y nunca se les concede EXECUTE a PUBLIC.
--
-- Códigos SQLSTATE propios (los traduce cada servicio a HTTP):
--   US001 usuario no existe · US002 sería el último administrador activo
--   AU001 autor no existe · AU002 libro no existe · AU003 ya vinculado · AU004 vínculo no existe
-- Requiere 006 y 007. Ejecutar como library_user (dueño):
--   PGPASSWORD=... psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/008_users_authors_functions.sql
-- =====================================================================
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
  IF to_regclass('public.roles') IS NULL
     OR NOT EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'role_id') THEN
    RAISE EXCEPTION 'Falta users.role_id: ejecuta antes 006_roles.sql';
  END IF;
  IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('users_service_user', 'authors_service_user')) < 2 THEN
    RAISE EXCEPTION 'Faltan los roles de BD: ejecuta antes 007_service_db_roles.sql (como postgres)';
  END IF;
END $$;

-- ============================ USERS ==================================
-- Nunca devuelve password_hash salvo fn_users_get_password_hash (cambio de contraseña).
CREATE OR REPLACE FUNCTION fn_users_list(p_limit integer DEFAULT 50, p_offset integer DEFAULT 0)
RETURNS TABLE (user_id bigint, email varchar, display_name varchar, nombre varchar,
               apellido_paterno varchar, apellido_materno varchar, role_id smallint,
               role_name varchar, is_active boolean, email_verified_at timestamptz, created_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT u.user_id, u.email, u.display_name, u.nombre, u.apellido_paterno, u.apellido_materno,
           u.role_id, r.name, u.is_active, u.email_verified_at, u.created_at
      FROM users u JOIN roles r ON r.role_id = u.role_id
     ORDER BY u.user_id
     LIMIT greatest(least(coalesce(p_limit, 50), 200), 1)
    OFFSET greatest(coalesce(p_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION fn_users_get(p_user_id bigint)
RETURNS TABLE (user_id bigint, email varchar, display_name varchar, nombre varchar,
               apellido_paterno varchar, apellido_materno varchar, role_id smallint,
               role_name varchar, is_active boolean, email_verified_at timestamptz, created_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT u.user_id, u.email, u.display_name, u.nombre, u.apellido_paterno, u.apellido_materno,
           u.role_id, r.name, u.is_active, u.email_verified_at, u.created_at
      FROM users u JOIN roles r ON r.role_id = u.role_id
     WHERE u.user_id = p_user_id;
$$;

CREATE OR REPLACE FUNCTION fn_users_get_password_hash(p_user_id bigint)
RETURNS text
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT password_hash FROM users WHERE user_id = p_user_id;
$$;

-- Alta hecha por un administrador: el correo nace verificado; is_admin NO se toca (queda false).
CREATE OR REPLACE FUNCTION fn_users_create(
    p_email varchar, p_password_hash text, p_display_name varchar,
    p_nombre varchar, p_apellido_paterno varchar, p_apellido_materno varchar, p_role_id smallint)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_id bigint;
BEGIN
    INSERT INTO users (email, password_hash, display_name, nombre, apellido_paterno, apellido_materno,
                       role_id, email_verified_at)
    VALUES (lower(btrim(p_email)), p_password_hash, btrim(p_display_name), p_nombre, p_apellido_paterno,
            p_apellido_materno, coalesce(p_role_id, 3), CURRENT_TIMESTAMP)
    RETURNING user_id INTO v_id;
    RETURN v_id;
END $$;

-- PATCH: NULL = conservar el valor actual.
CREATE OR REPLACE FUNCTION fn_users_update(
    p_user_id bigint, p_email varchar, p_display_name varchar, p_nombre varchar,
    p_apellido_paterno varchar, p_apellido_materno varchar, p_role_id smallint, p_is_active boolean)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_old users%ROWTYPE;
BEGIN
    SELECT * INTO v_old FROM users WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe el usuario %', p_user_id USING ERRCODE = 'US001';
    END IF;
    IF v_old.role_id = 1 AND v_old.is_active
       AND ((p_role_id IS NOT NULL AND p_role_id <> 1) OR coalesce(p_is_active, true) = false)
       AND NOT EXISTS (SELECT 1 FROM users WHERE role_id = 1 AND is_active AND user_id <> p_user_id) THEN
        RAISE EXCEPTION 'No se puede quitar al último administrador activo' USING ERRCODE = 'US002';
    END IF;
    UPDATE users
       SET email = coalesce(lower(btrim(p_email)), email),
           display_name = coalesce(btrim(p_display_name), display_name),
           nombre = coalesce(p_nombre, nombre),
           apellido_paterno = coalesce(p_apellido_paterno, apellido_paterno),
           apellido_materno = coalesce(p_apellido_materno, apellido_materno),
           role_id = coalesce(p_role_id, role_id),
           is_active = coalesce(p_is_active, is_active)
     WHERE user_id = p_user_id;
END $$;

CREATE OR REPLACE FUNCTION fn_users_set_password(p_user_id bigint, p_password_hash text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE users SET password_hash = p_password_hash WHERE user_id = p_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe el usuario %', p_user_id USING ERRCODE = 'US001';
    END IF;
END $$;

-- Un usuario con pedidos no se puede borrar (FK RESTRICT => 23503): se desactiva con fn_users_update.
CREATE OR REPLACE FUNCTION fn_users_delete(p_user_id bigint)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_old users%ROWTYPE;
BEGIN
    SELECT * INTO v_old FROM users WHERE user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe el usuario %', p_user_id USING ERRCODE = 'US001';
    END IF;
    IF v_old.role_id = 1 AND v_old.is_active
       AND NOT EXISTS (SELECT 1 FROM users WHERE role_id = 1 AND is_active AND user_id <> p_user_id) THEN
        RAISE EXCEPTION 'No se puede borrar al último administrador activo' USING ERRCODE = 'US002';
    END IF;
    DELETE FROM users WHERE user_id = p_user_id;
END $$;

-- ============================ AUTHORS ================================
CREATE OR REPLACE FUNCTION fn_authors_list(p_limit integer DEFAULT 50, p_offset integer DEFAULT 0)
RETURNS TABLE (author_id bigint, first_name varchar, last_name varchar, biography text,
               books_count bigint, created_at timestamptz, updated_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT a.author_id, a.first_name, a.last_name, a.biography,
           (SELECT count(*) FROM book_authors ba WHERE ba.author_id = a.author_id),
           a.created_at, a.updated_at
      FROM authors a
     ORDER BY a.last_name NULLS LAST, a.first_name, a.author_id
     LIMIT greatest(least(coalesce(p_limit, 50), 200), 1)
    OFFSET greatest(coalesce(p_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION fn_authors_get(p_author_id bigint)
RETURNS TABLE (author_id bigint, first_name varchar, last_name varchar, biography text,
               books_count bigint, created_at timestamptz, updated_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT a.author_id, a.first_name, a.last_name, a.biography,
           (SELECT count(*) FROM book_authors ba WHERE ba.author_id = a.author_id),
           a.created_at, a.updated_at
      FROM authors a WHERE a.author_id = p_author_id;
$$;

CREATE OR REPLACE FUNCTION fn_authors_books(p_author_id bigint)
RETURNS TABLE (book_id bigint, isbn varchar, title varchar, author_order smallint)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT b.book_id, b.isbn, b.title, ba.author_order
      FROM book_authors ba JOIN books b ON b.book_id = ba.book_id
     WHERE ba.author_id = p_author_id
     ORDER BY b.title;
$$;

CREATE OR REPLACE FUNCTION fn_authors_create(p_first_name varchar, p_last_name varchar, p_biography text)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_id bigint;
BEGIN
    INSERT INTO authors (first_name, last_name, biography)
    VALUES (btrim(p_first_name), nullif(btrim(p_last_name), ''), p_biography)
    RETURNING author_id INTO v_id;
    RETURN v_id;
END $$;

-- p_replace = true (PUT): reemplaza todo; false (PATCH): NULL = conservar.
CREATE OR REPLACE FUNCTION fn_authors_update(
    p_author_id bigint, p_first_name varchar, p_last_name varchar, p_biography text, p_replace boolean)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF p_replace THEN
        UPDATE authors SET first_name = btrim(p_first_name), last_name = nullif(btrim(p_last_name), ''),
                           biography = p_biography
         WHERE author_id = p_author_id;
    ELSE
        UPDATE authors SET first_name = coalesce(btrim(p_first_name), first_name),
                           last_name = coalesce(nullif(btrim(p_last_name), ''), last_name),
                           biography = coalesce(p_biography, biography)
         WHERE author_id = p_author_id;
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe el autor %', p_author_id USING ERRCODE = 'AU001';
    END IF;
END $$;

-- Un autor con libros no se borra (FK RESTRICT => 23503): primero hay que desvincularlo.
CREATE OR REPLACE FUNCTION fn_authors_delete(p_author_id bigint)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    DELETE FROM authors WHERE author_id = p_author_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe el autor %', p_author_id USING ERRCODE = 'AU001';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION fn_authors_link_book(p_author_id bigint, p_isbn varchar, p_author_order smallint)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_book_id bigint;
    v_order smallint;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM authors WHERE author_id = p_author_id) THEN
        RAISE EXCEPTION 'No existe el autor %', p_author_id USING ERRCODE = 'AU001';
    END IF;
    SELECT book_id INTO v_book_id FROM books WHERE isbn = btrim(p_isbn);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe un libro con ISBN %', p_isbn USING ERRCODE = 'AU002';
    END IF;
    IF EXISTS (SELECT 1 FROM book_authors WHERE book_id = v_book_id AND author_id = p_author_id) THEN
        RAISE EXCEPTION 'El autor ya está vinculado a ese libro' USING ERRCODE = 'AU003';
    END IF;
    SELECT coalesce(p_author_order, coalesce(max(author_order), 0) + 1) INTO v_order
      FROM book_authors WHERE book_id = v_book_id;
    INSERT INTO book_authors (book_id, author_id, author_order) VALUES (v_book_id, p_author_id, v_order);
END $$;

CREATE OR REPLACE FUNCTION fn_authors_unlink_book(p_author_id bigint, p_isbn varchar)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    DELETE FROM book_authors
     WHERE author_id = p_author_id
       AND book_id = (SELECT book_id FROM books WHERE isbn = btrim(p_isbn));
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe ese vínculo autor-libro' USING ERRCODE = 'AU004';
    END IF;
END $$;

-- ============================ PERMISOS ===============================
-- PostgreSQL concede EXECUTE a PUBLIC por defecto: se revoca y se otorga solo al rol del servicio.
DO $$
DECLARE
    r record;
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO users_service_user, authors_service_user', current_database());
    GRANT USAGE ON SCHEMA public TO users_service_user, authors_service_user;

    FOR r IN SELECT p.oid::regprocedure AS sig, p.proname
               FROM pg_proc p
              WHERE p.pronamespace = 'public'::regnamespace
                AND (p.proname LIKE 'fn\_users\_%' OR p.proname LIKE 'fn\_authors\_%') LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', r.sig);
        IF r.proname LIKE 'fn\_users\_%' THEN
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO users_service_user', r.sig);
        ELSE
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO authors_service_user', r.sig);
        END IF;
    END LOOP;
END $$;

COMMIT;
