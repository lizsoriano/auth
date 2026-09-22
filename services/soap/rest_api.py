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

from flask import jsonify, request

from db import connection, repository


def quiere_json():
    """Único punto de decisión XML-vs-JSON, usado por las 4 rutas de abajo:
    ?format=json -> JSON; cualquier otro valor u omitido -> XML (regla
    exacta del punto 4 de la actividad)."""
    return request.args.get("format", "").strip().lower() == "json"


def _xml_response(root_el):
    body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root_el, encoding="utf-8")
    return body, {"Content-Type": "application/xml"}


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

def listar_libros_view():
    with connection.get_connection() as conn:
        libros = [_libro_a_dict(b) for b in repository.listar_libros(conn)]

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
    with connection.get_connection() as conn:
        libros = [_libro_a_dict(b) for b in repository.listar_libros(conn)]
    libro = next((b for b in libros if b["isbn"] == isbn), None)

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


def register(app):
    """Registra las 4 rutas en la app Flask existente (app.py)."""
    app.add_url_rule("/books", "listar_libros", listar_libros_view, methods=["GET"])
    app.add_url_rule("/books/images", "listar_libros_con_imagenes", listar_libros_con_imagenes_view, methods=["GET"])
    app.add_url_rule("/books/<isbn>", "obtener_libro", obtener_libro_view, methods=["GET"])
    app.add_url_rule("/concepts", "listar_conceptos", listar_conceptos_view, methods=["GET"])
