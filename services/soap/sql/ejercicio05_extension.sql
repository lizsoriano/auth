-- sql/ejercicio05_extension.sql
-- Actividad en clase: microservicio SOAP "bilingue" (XML + JSON via
-- ?format=json). Puramente aditivo sobre sql/soap_module.sql (Ejercicio
-- Guiado 03, sin modificar): no se toca ninguna tabla, funcion ni GRANT
-- ya existente.
--
-- Mismo criterio de minimo privilegio que el resto del proyecto (ED-11):
-- en vez de otorgar SELECT directo sobre books/book_images a
-- soap_service_user, se agregan dos funciones SECURITY DEFINER nuevas
-- (mismo patron que fn_conceptos_pendientes) y solo se otorga EXECUTE
-- sobre ellas. soap_service_user sigue sin poder leer ninguna tabla
-- directamente.

-- =========================================================================
-- fn_listar_libros: datos minimos de todos los libros (isbn, titulo,
-- precio, categoria). Fuente para GET /books y GET /books/<isbn> (este
-- ultimo filtra por isbn en Python sobre el mismo resultado, para no
-- duplicar la consulta).
-- =========================================================================
CREATE OR REPLACE FUNCTION fn_listar_libros()
RETURNS TABLE (
    book_id bigint,
    isbn varchar,
    title varchar,
    price numeric,
    category varchar
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT b.book_id, b.isbn, b.title, b.price, c.name
    FROM books b
    JOIN categories c USING (category_id)
    ORDER BY b.title;
$$;

-- =========================================================================
-- fn_libros_con_imagenes: datos minimos de cada libro junto con sus
-- imagenes (una fila por imagen; un libro sin imagenes no aparece -- ver
-- LEFT JOIN si se prefiere lo contrario). Fuente del endpoint del punto 6
-- de la actividad.
-- =========================================================================
CREATE OR REPLACE FUNCTION fn_libros_con_imagenes()
RETURNS TABLE (
    book_id bigint,
    isbn varchar,
    title varchar,
    image_url text,
    is_cover boolean
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT b.book_id, b.isbn, b.title, bi.image_url, bi.is_cover
    FROM books b
    JOIN book_images bi USING (book_id)
    ORDER BY b.title, bi.display_order;
$$;

GRANT EXECUTE ON FUNCTION fn_listar_libros() TO soap_service_user;
GRANT EXECUTE ON FUNCTION fn_libros_con_imagenes() TO soap_service_user;

-- Nota: el endpoint de conceptos de Cloud Computing (punto 5 de la
-- actividad) NO necesita SQL nuevo -- reutiliza fn_conceptos_pendientes
-- (ya otorgada a soap_service_user en sql/soap_module.sql), llamada sin
-- filtros: "Si filtroCorreo se omite, devuelve el catalogo completo de
-- conceptos clasificables" (ver db/repository.py, docstring de
-- listar_conceptos_pendientes).
