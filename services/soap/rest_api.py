"""Endpoints REST "bilingües" (XML/JSON) -- actividad en clase: hacer del
microservicio SOAP ya existente un microservicio que también conteste en
JSON cuando se pide `?format=json`, sin dejar de responder XML por
defecto (comportamiento actual de app.py: GET /wsdl y POST /soap no se
tocan).

Estas rutas son deliberadamente independientes del despacho SOAP
(soap/service.py, soap/envelope.py): no son operaciones de un contrato
WSDL, son recursos REST simples sobre los mismos datos, así que su XML es
un documento plano (`<books>...</books>`), no un soap:Envelope -- no
tendría sentido envolver un GET sin Body en un sobre SOAP.

Reutiliza exclusivamente accesos a datos que ya existen o que son la
extensión mínima de ese mismo patrón (ver db/repository.py y
sql/ejercicio05_extension.sql): nada de lógica de negocio nueva aquí,
solo parseo del query param `format` y serialización.
"""
import xml.etree.ElementTree as ET

from flask import current_app, jsonify, request
from library_common import ROLE_ADMIN, ROLE_STAFF, book_key, books_list_key, invalidate_books

from db import connection, repository
from db.errors import LibroInvalidoError, LibroNoEncontradoError


def quiere_json():
    """Único punto de decisión XML-vs-JSON, usado por las 4 rutas de abajo:
    ?format=json -> JSON; cualquier otro valor u omitido -> XML (regla
    exacta del punto 4 de la actividad)."""
    return request.args.get("format", "").strip().lower() == "json"


def _xml_response(root_el):
    body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root_el, encoding="utf-8")
    return body, {"Content-Type": "application/xml"}


def _error(mensaje, status):
    if quiere_json():
        return jsonify({"error": mensaje}), status
    root = ET.Element("error")
    ET.SubElement(root, "message").text = mensaje
    body, headers = _xml_response(root)
    return body, status, headers


def _cuerpo():
    """Cuerpo de POST/PUT: JSON (Content-Type: application/json) o
    formulario -- lo que sea más cómodo para probar con curl/Postman o
    para la app de escritorio (Electron/Tkinter)."""
    if request.is_json:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}
    return request.form.to_dict()


_CAMPOS_LIBRO = ("isbn", "title", "publicationYear", "price", "stock", "category", "format", "authors")


def _datos_libro(data, requiere_isbn):
    """Valida presencia/tipo de los campos del formulario de alta/edición.
    Devuelve (kwargs_para_repository, None) o (None, mensaje_de_error)."""
    faltantes = [c for c in _CAMPOS_LIBRO if c != "authors" and not str(data.get(c, "")).strip()
                and not (c == "isbn" and not requiere_isbn)]
    if faltantes:
        return None, f"Faltan campos obligatorios: {', '.join(faltantes)}"
    try:
        publication_year = int(data["publicationYear"])
        price = float(data["price"])
        stock = int(data.get("stock", 0) or 0)
    except (TypeError, ValueError):
        return None, "publicationYear, price y stock deben ser numéricos"
    return {
        "title": str(data["title"]).strip(),
        "publication_year": publication_year,
        "price": price,
        "stock": stock,
        "category": str(data["category"]).strip(),
        "format": str(data["format"]).strip(),
        "authors": str(data.get("authors", "")).strip(),
    }, None


def _libro_a_dict(libro):
    """Normaliza tipos no serializables a JSON (Decimal -> float) en un
    solo lugar, usado tanto por la rama JSON como por la XML de /books."""
    return {
        "bookId": libro["book_id"],
        "isbn": libro["isbn"],
        "title": libro["title"],
        "price": float(libro["price"]),
        "category": libro["category"],
        "stock": libro["stock"],
        "publicationYear": libro["publication_year"],
        "authors": libro["authors"],
    }


# --------------------------------------------------------------------
# GET /books  y  GET /books/<isbn>
# --------------------------------------------------------------------

def _svc():
    """Redis, métricas y TTL de este servicio (los pone app.create_app)."""
    return current_app.extensions["books"]


def _libros_cacheados():
    """Lista de libros: de Redis si está (books:list:all, TTL corto); si no, de PostgreSQL y se guarda.

    La caché es OPCIONAL: si Redis falla, RedisLayer cuenta el error y devuelve "no hay dato", y se lee de PostgreSQL.
    Se guarda el dict (no el XML/JSON ya armado), así una sola entrada sirve para ?format=xml y ?format=json.
    """
    svc = _svc()
    key = books_list_key(request.args)
    cached = svc.redis.cache_get(key)
    if cached is not None:
        return cached
    with connection.get_connection() as conn:
        libros = [_libro_a_dict(b) for b in repository.listar_libros(conn)]
    svc.redis.cache_set(key, libros, svc.cache_ttl)
    return libros


def listar_libros_view():
    libros = _libros_cacheados()

    if quiere_json():
        return jsonify({"books": libros})

    root = ET.Element("books")
    for b in libros:
        book_el = ET.SubElement(root, "book")
        ET.SubElement(book_el, "bookId").text = str(b["bookId"])
        ET.SubElement(book_el, "isbn").text = b["isbn"]
        ET.SubElement(book_el, "title").text = b["title"]
        ET.SubElement(book_el, "price").text = str(b["price"])
        ET.SubElement(book_el, "category").text = b["category"]
        ET.SubElement(book_el, "stock").text = str(b["stock"])
        ET.SubElement(book_el, "publicationYear").text = str(b["publicationYear"])
        ET.SubElement(book_el, "authors").text = b["authors"]
    return _xml_response(root)


def obtener_libro_view(isbn):
    svc = _svc()
    key = book_key(isbn)  # None si no tiene forma de ISBN: no se cachea (evita claves arbitrarias en Redis)
    libro = svc.redis.cache_get(key) if key else None
    if libro is None:
        libro = next((b for b in _libros_cacheados() if b["isbn"] == isbn), None)
        if libro is not None and key:
            svc.redis.cache_set(key, libro, svc.cache_ttl)

    if libro is None:
        if quiere_json():
            return jsonify({"error": f"No existe un libro con isbn {isbn!r}."}), 404
        root = ET.Element("error")
        ET.SubElement(root, "message").text = f"No existe un libro con isbn {isbn!r}."
        body, headers = _xml_response(root)
        return body, 404, headers

    if quiere_json():
        return jsonify(libro)

    book_el = ET.Element("book")
    ET.SubElement(book_el, "bookId").text = str(libro["bookId"])
    ET.SubElement(book_el, "isbn").text = libro["isbn"]
    ET.SubElement(book_el, "title").text = libro["title"]
    ET.SubElement(book_el, "price").text = str(libro["price"])
    ET.SubElement(book_el, "category").text = libro["category"]
    ET.SubElement(book_el, "stock").text = str(libro["stock"])
    ET.SubElement(book_el, "publicationYear").text = str(libro["publicationYear"])
    ET.SubElement(book_el, "authors").text = libro["authors"]
    return _xml_response(book_el)


# --------------------------------------------------------------------
# GET /concepts -- punto 5: conceptos de Cloud Computing (IaaS/PaaS/SaaS/
# FaaS) junto con los datos de los libros. Reutiliza tal cual la consulta
# que ya usa la operación SOAP ObtenerConceptosPendientes sin filtros
# (repository.listar_conceptos_pendientes(conn, None, None) devuelve el
# catálogo completo -- ver su propio docstring).
# --------------------------------------------------------------------

def listar_conceptos_view():
    with connection.get_connection() as conn:
        conceptos, total = repository.listar_conceptos_pendientes(conn, None, None)

    if quiere_json():
        return jsonify({"concepts": conceptos, "total": total})

    root = ET.Element("concepts")
    for c in conceptos:
        el = ET.SubElement(root, "concept")
        ET.SubElement(el, "bookId").text = str(c["book_id"])
        ET.SubElement(el, "isbn").text = c["isbn"]
        ET.SubElement(el, "bookTitle").text = c["titulo_libro"]
        ET.SubElement(el, "category").text = c["categoria"]
        ET.SubElement(el, "conceptId").text = str(c["concepto_id"])
        ET.SubElement(el, "concept").text = c["concepto"]
        ET.SubElement(el, "definition").text = c["definicion"]
    ET.SubElement(root, "total").text = str(total)
    return _xml_response(root)


# --------------------------------------------------------------------
# GET /books/images -- punto 6: datos mínimos de los libros junto con sus
# imágenes.
# --------------------------------------------------------------------

def listar_libros_con_imagenes_view():
    with connection.get_connection() as conn:
        libros = repository.listar_libros_con_imagenes(conn)

    if quiere_json():
        return jsonify({"books": libros})

    root = ET.Element("books")
    for b in libros:
        book_el = ET.SubElement(root, "book")
        ET.SubElement(book_el, "bookId").text = str(b["book_id"])
        ET.SubElement(book_el, "isbn").text = b["isbn"]
        ET.SubElement(book_el, "title").text = b["title"]
        images_el = ET.SubElement(book_el, "images")
        for img in b["images"]:
            img_el = ET.SubElement(images_el, "image")
            ET.SubElement(img_el, "url").text = img["url"]
            ET.SubElement(img_el, "isCover").text = "true" if img["is_cover"] else "false"
    return _xml_response(root)


# --------------------------------------------------------------------
# CRUD del catálogo -- "un usuario registrado puede hacer las operaciones
# CRUD" (ver sql/crud_libros_extension.sql). Las 4 escrituras de abajo
# exigen el JWT que emite POST /login del microservicio de autenticación
# (ver auth_jwt.py); las lecturas (GET) siguen públicas, sin cambios.
# --------------------------------------------------------------------

def crear_libro_view():
    data = _cuerpo()
    if not str(data.get("isbn", "")).strip():
        return _error("El campo isbn es obligatorio", 400)
    campos, mensaje = _datos_libro(data, requiere_isbn=True)
    if mensaje:
        return _error(mensaje, 400)
    try:
        with connection.get_connection() as conn:
            book_id = repository.crear_libro(conn, isbn=str(data["isbn"]).strip(), **campos)
    except LibroInvalidoError as exc:
        return _error(str(exc), 409 if "ya existe" in str(exc).lower() else 400)
    invalidate_books(_svc().redis, [str(data["isbn"]).strip()])

    payload = {"bookId": book_id, "isbn": str(data["isbn"]).strip(), **campos}
    if quiere_json():
        return jsonify(payload), 201
    root = ET.Element("book")
    ET.SubElement(root, "bookId").text = str(book_id)
    ET.SubElement(root, "isbn").text = payload["isbn"]
    ET.SubElement(root, "title").text = payload["title"]
    body, headers = _xml_response(root)
    return body, 201, headers


def actualizar_libro_view(isbn):
    data = _cuerpo()
    campos, mensaje = _datos_libro(data, requiere_isbn=False)
    if mensaje:
        return _error(mensaje, 400)
    try:
        with connection.get_connection() as conn:
            repository.actualizar_libro(conn, isbn=isbn, **campos)
    except LibroNoEncontradoError as exc:
        return _error(str(exc), 404)
    except LibroInvalidoError as exc:
        return _error(str(exc), 400)
    invalidate_books(_svc().redis, [isbn])
    return respond_message_ok(f"Libro {isbn} actualizado correctamente.")


def parchear_libro_view(isbn):
    """PATCH /books/<isbn>: a diferencia de PUT (que exige mandar TODOS los
    campos y reemplaza el libro completo), aquí solo se envían los campos
    que cambian -- lo que NO se manda viaja como NULL y fn_actualizar_libro
    conserva el valor que el libro ya tenía (ver sql/crud_libros_extension.sql)."""
    data = _cuerpo()
    if not data:
        return _error("Envía al menos un campo para modificar (PATCH no reemplaza el libro completo)", 400)

    def numero(nombre, castear):
        if nombre not in data:
            return None, None
        try:
            return castear(data[nombre]), None
        except (TypeError, ValueError):
            return None, f"{nombre} debe ser numérico"

    publication_year, err1 = numero("publicationYear", int)
    price, err2 = numero("price", float)
    stock, err3 = numero("stock", int)
    error = err1 or err2 or err3
    if error:
        return _error(error, 400)

    campos = {
        "title": str(data["title"]).strip() if "title" in data else None,
        "publication_year": publication_year,
        "price": price,
        "stock": stock,
        "category": str(data["category"]).strip() if "category" in data else None,
        "format": str(data["format"]).strip() if "format" in data else None,
        "authors": str(data["authors"]).strip() if "authors" in data else None,
    }
    try:
        with connection.get_connection() as conn:
            repository.actualizar_libro(conn, isbn=isbn, **campos)
    except LibroNoEncontradoError as exc:
        return _error(str(exc), 404)
    except LibroInvalidoError as exc:
        return _error(str(exc), 400)
    invalidate_books(_svc().redis, [isbn])
    return respond_message_ok(f"Libro {isbn} modificado (parcial) correctamente.")


def eliminar_libro_view(isbn):
    try:
        with connection.get_connection() as conn:
            repository.eliminar_libro(conn, isbn)
    except LibroNoEncontradoError as exc:
        return _error(str(exc), 404)
    invalidate_books(_svc().redis, [isbn])
    return respond_message_ok(f"Libro {isbn} eliminado correctamente.")


def respond_message_ok(mensaje):
    if quiere_json():
        return jsonify({"message": mensaje})
    root = ET.Element("response")
    ET.SubElement(root, "message").text = mensaje
    return _xml_response(root)


# --------------------------------------------------------------------
# GET /health -- estado del microservicio y de PostgreSQL (mismo criterio
# que services/login/login_service/routes.py: no revela detalles internos
# del error, solo si la base responde).
# --------------------------------------------------------------------

def health_view():
    try:
        with connection.get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            conn.commit()
    except Exception:
        return _error("El servicio está activo pero PostgreSQL no está disponible", 503)
    # Redis es OPCIONAL para las lecturas: si no responde el servicio sigue sano (degradado), pero los
    # POST/PUT/PATCH/DELETE devuelven 503 porque no pueden verificar la revocación del JWT.
    payload = {"status": "ok", "service": "soap", "database": "connected",
               "redis": "ok" if _svc().redis.ping() else "unavailable"}
    if quiere_json():
        return jsonify(payload)
    root = ET.Element("response")
    for k, v in payload.items():
        ET.SubElement(root, k).text = v
    return _xml_response(root)


def jwt_error_response(code, message, status):
    """Cómo responde books cuando el JWT falla (mismo formato que sus demás errores)."""
    return _error(message, status)


def register(app, *, jwt_auth):
    """Registra las rutas REST en la app Flask (app.create_app).

    Las GET son públicas. POST/PUT/PATCH/DELETE exigen `Authorization: Bearer <JWT>` válido (firma, HS256,
    expiración, claims, no revocado) y rol admin o staff: 401 sin token/inválido, 403 con rol insuficiente.
    """
    write = jwt_auth.required(roles=(ROLE_ADMIN, ROLE_STAFF))
    app.add_url_rule("/books", "listar_libros", listar_libros_view, methods=["GET"])
    app.add_url_rule("/books", "crear_libro", write(crear_libro_view), methods=["POST"])
    app.add_url_rule("/books/images", "listar_libros_con_imagenes", listar_libros_con_imagenes_view, methods=["GET"])
    app.add_url_rule("/books/<isbn>", "obtener_libro", obtener_libro_view, methods=["GET"])
    app.add_url_rule("/books/<isbn>", "actualizar_libro", write(actualizar_libro_view), methods=["PUT"])
    app.add_url_rule("/books/<isbn>", "parchear_libro", write(parchear_libro_view), methods=["PATCH"])
    app.add_url_rule("/books/<isbn>", "eliminar_libro", write(eliminar_libro_view), methods=["DELETE"])
    app.add_url_rule("/concepts", "listar_conceptos", listar_conceptos_view, methods=["GET"])
    app.add_url_rule("/health", "health", health_view, methods=["GET"])
