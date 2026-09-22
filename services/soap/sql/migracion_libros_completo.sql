-- sql/migracion_libros_completo.sql
-- Extiende fn_listar_libros (sql/ejercicio05_extension.sql) para incluir
-- stock, publication_year y autor(es) -- campos que pide la app de
-- Electron (04_Electron.app.md, punto 1) y que la primera version de esta
-- funcion no exponia (solo book_id/isbn/title/price/category).
--
-- Mismo patron de minimo privilegio del resto del proyecto: SECURITY
-- DEFINER + solo EXECUTE a soap_service_user, ningun GRANT nuevo sobre
-- books/authors/book_authors (que soap_service_user sigue sin poder leer
-- directamente).
--
-- Requiere un rol con permiso para reemplazar fn_listar_libros (su dueño
-- actual, library_user, o un superusuario) -- soap_service_user NO
-- alcanza para esto.

DROP FUNCTION IF EXISTS fn_listar_libros();

CREATE FUNCTION fn_listar_libros()
RETURNS TABLE (
    book_id bigint,
    isbn varchar,
    title varchar,
    price numeric,
    category varchar,
    stock integer,
    publication_year smallint,
    authors text
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        b.book_id, b.isbn, b.title, b.price, c.name,
        b.stock, b.publication_year,
        COALESCE(
            string_agg(
                trim(both ' ' from a.first_name || ' ' || COALESCE(a.last_name, '')),
                ', ' ORDER BY ba.author_order
            ),
            ''
        )
    FROM books b
    JOIN categories c USING (category_id)
    LEFT JOIN book_authors ba USING (book_id)
    LEFT JOIN authors a USING (author_id)
    GROUP BY b.book_id, b.isbn, b.title, b.price, c.name, b.stock, b.publication_year
    ORDER BY b.title;
$$;

GRANT EXECUTE ON FUNCTION fn_listar_libros() TO soap_service_user;
