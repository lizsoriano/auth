-- sql/crud_libros_extension.sql
-- Actividad en clase: "un usuario registrado puede hacer las operaciones
-- CRUD" sobre el catálogo. Puramente aditivo sobre sql/soap_module.sql y
-- sql/ejercicio05_extension.sql: no se toca ninguna tabla, función ni
-- GRANT ya existente.
--
-- Mismo criterio de mínimo privilegio del resto del proyecto (ED-11):
-- tres funciones SECURITY DEFINER nuevas (crear/actualizar/eliminar) y
-- solo se otorga EXECUTE sobre ellas. soap_service_user sigue sin poder
-- leer ni escribir ninguna tabla directamente.
--
-- Autenticación: el "usuario registrado" del enunciado se valida en el
-- microservicio login (servicio aparte, puerto 5000) antes de que la
-- aplicación de escritorio muestre el catálogo con los botones de
-- EDITAR/ELIMINAR/AGREGAR. Este módulo (books) no repite esa validación
-- -- son dos microservicios independientes a propósito (ver README) --
-- así que estas funciones no comprueban sesión alguna; su superficie
-- expuesta ya está acotada al mínimo (autores/categoría/formato, no DDL
-- ni acceso a books/authors fuera de estas 3 funciones).
--
-- Requiere un rol con permiso para crear funciones (su dueño actual,
-- library_user, o un superusuario) -- soap_service_user NO alcanza para
-- esto.

-- =========================================================================
-- fn_crear_libro: alta de un libro. Categoría y formato se crean si no
-- existen (evita que la app de escritorio necesite un catálogo aparte
-- para darlos de alta); autor(es) igual, buscando por nombre completo
-- exacto y creando uno nuevo si no hay coincidencia.
-- =========================================================================
CREATE OR REPLACE FUNCTION fn_crear_libro(
    p_isbn varchar,
    p_title varchar,
    p_publication_year integer,
    p_price numeric,
    p_stock integer,
    p_category varchar,
    p_format varchar,
    p_authors varchar  -- nombres completos separados por coma, p. ej. "George Orwell, Aldous Huxley"
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_category_id bigint;
    v_format_id bigint;
    v_book_id bigint;
    v_nombre text;
    v_author_id bigint;
    v_primer_nombre text;
    v_apellido text;
    v_orden smallint := 0;
BEGIN
    IF btrim(coalesce(p_isbn, '')) = '' THEN
        RAISE EXCEPTION 'El ISBN es obligatorio' USING ERRCODE = 'CB001';
    END IF;
    IF btrim(coalesce(p_title, '')) = '' THEN
        RAISE EXCEPTION 'El título es obligatorio' USING ERRCODE = 'CB002';
    END IF;

    INSERT INTO categories (name) VALUES (btrim(p_category))
        ON CONFLICT (name) DO NOTHING;
    SELECT category_id INTO v_category_id FROM categories WHERE name = btrim(p_category);

    INSERT INTO formats (name) VALUES (btrim(p_format))
        ON CONFLICT (name) DO NOTHING;
    SELECT format_id INTO v_format_id FROM formats WHERE name = btrim(p_format);

    INSERT INTO books (isbn, title, publication_year, price, stock, format_id, category_id)
    VALUES (btrim(p_isbn), btrim(p_title), p_publication_year, p_price, coalesce(p_stock, 0),
            v_format_id, v_category_id)
    RETURNING book_id INTO v_book_id;

    FOR v_nombre IN
        SELECT btrim(x) FROM unnest(string_to_array(coalesce(p_authors, ''), ',')) AS x
         WHERE btrim(x) <> ''
    LOOP
        v_orden := v_orden + 1;
        -- último espacio separa "nombre" de "apellido(s)"; sin espacio, todo es el nombre.
        v_apellido := NULLIF(btrim(substring(v_nombre FROM '\s(\S+)$')), '');
        v_primer_nombre := CASE WHEN v_apellido IS NULL THEN v_nombre
                                ELSE btrim(substring(v_nombre FROM '^(.*)\s\S+$')) END;
        SELECT author_id INTO v_author_id FROM authors
         WHERE first_name = v_primer_nombre AND coalesce(last_name, '') = coalesce(v_apellido, '')
         LIMIT 1;
        IF v_author_id IS NULL THEN
            INSERT INTO authors (first_name, last_name) VALUES (v_primer_nombre, v_apellido)
                RETURNING author_id INTO v_author_id;
        END IF;
        INSERT INTO book_authors (book_id, author_id, author_order) VALUES (v_book_id, v_author_id, v_orden);
    END LOOP;

    RETURN v_book_id;
END;
$$;

-- =========================================================================
-- fn_actualizar_libro: reemplaza los datos propios del libro y su lista
-- de autores (borra y vuelve a insertar book_authors -- más simple y
-- suficientemente rápido para el tamaño de este catálogo). No toca isbn
-- si se manda NULL (permite editar solo algunos campos).
-- =========================================================================
CREATE OR REPLACE FUNCTION fn_actualizar_libro(
    p_isbn varchar,
    p_title varchar,
    p_publication_year integer,
    p_price numeric,
    p_stock integer,
    p_category varchar,
    p_format varchar,
    p_authors varchar
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_book_id bigint;
    v_category_id bigint;
    v_format_id bigint;
    v_nombre text;
    v_author_id bigint;
    v_primer_nombre text;
    v_apellido text;
    v_orden smallint := 0;
BEGIN
    SELECT book_id, category_id, format_id INTO v_book_id, v_category_id, v_format_id
      FROM books WHERE isbn = btrim(p_isbn);
    IF v_book_id IS NULL THEN
        RETURN false;
    END IF;

    -- p_category/p_format en NULL (PATCH parcial que no los manda) conserva
    -- el catálogo actual del libro en vez de borrarlo; PUT (que siempre los
    -- manda) se comporta igual que antes.
    IF p_category IS NOT NULL THEN
        INSERT INTO categories (name) VALUES (btrim(p_category)) ON CONFLICT (name) DO NOTHING;
        SELECT category_id INTO v_category_id FROM categories WHERE name = btrim(p_category);
    END IF;

    IF p_format IS NOT NULL THEN
        INSERT INTO formats (name) VALUES (btrim(p_format)) ON CONFLICT (name) DO NOTHING;
        SELECT format_id INTO v_format_id FROM formats WHERE name = btrim(p_format);
    END IF;

    UPDATE books SET
        title = coalesce(btrim(p_title), title),
        publication_year = coalesce(p_publication_year, publication_year),
        price = coalesce(p_price, price),
        stock = coalesce(p_stock, stock),
        category_id = v_category_id,
        format_id = v_format_id,
        updated_at = CURRENT_TIMESTAMP
    WHERE book_id = v_book_id;

    -- p_authors en NULL (PATCH que no lo manda) conserva los autores
    -- actuales en vez de borrarlos.
    IF p_authors IS NOT NULL THEN
        DELETE FROM book_authors WHERE book_id = v_book_id;
        FOR v_nombre IN
            SELECT btrim(x) FROM unnest(string_to_array(p_authors, ',')) AS x
             WHERE btrim(x) <> ''
        LOOP
            v_orden := v_orden + 1;
            v_apellido := NULLIF(btrim(substring(v_nombre FROM '\s(\S+)$')), '');
            v_primer_nombre := CASE WHEN v_apellido IS NULL THEN v_nombre
                                    ELSE btrim(substring(v_nombre FROM '^(.*)\s\S+$')) END;
            SELECT author_id INTO v_author_id FROM authors
             WHERE first_name = v_primer_nombre AND coalesce(last_name, '') = coalesce(v_apellido, '')
             LIMIT 1;
            IF v_author_id IS NULL THEN
                INSERT INTO authors (first_name, last_name) VALUES (v_primer_nombre, v_apellido)
                    RETURNING author_id INTO v_author_id;
            END IF;
            INSERT INTO book_authors (book_id, author_id, author_order) VALUES (v_book_id, v_author_id, v_orden);
        END LOOP;
    END IF;

    RETURN true;
END;
$$;

-- =========================================================================
-- fn_eliminar_libro: baja de un libro (por isbn, como el resto de la API
-- REST). ON DELETE CASCADE ya definido en book_authors/book_genres/
-- book_concepts/book_images se encarga del resto (ver data/schema.sql) --
-- esta función no duplica esa lógica.
-- =========================================================================
CREATE OR REPLACE FUNCTION fn_eliminar_libro(p_isbn varchar)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    DELETE FROM books WHERE isbn = btrim(p_isbn);
    RETURN FOUND;
END;
$$;

GRANT EXECUTE ON FUNCTION fn_crear_libro(varchar, varchar, integer, numeric, integer, varchar, varchar, varchar)
    TO soap_service_user;
GRANT EXECUTE ON FUNCTION fn_actualizar_libro(varchar, varchar, integer, numeric, integer, varchar, varchar, varchar)
    TO soap_service_user;
GRANT EXECUTE ON FUNCTION fn_eliminar_libro(varchar) TO soap_service_user;
