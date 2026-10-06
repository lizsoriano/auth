"""Rutas de Authors.

Lecturas (GET): públicas, con caché Redis de TTL corto (authors:list:<limit>, authors:<id>).
Escrituras (POST/PUT/PATCH/DELETE): JWT HS256 válido y rol admin o staff (401 sin token/inválido, 403 con otro rol).
Todo cambio de un autor invalida su caché Y la del catálogo (books:*): /books muestra los autores de cada libro.
"""
from flask import current_app
from library_common import ROLE_ADMIN, ROLE_STAFF, ApiError, invalidate_all_books
from library_common.serializers import render
from library_common.service_kit import json_body, page_args

NAME_MAX = 120
BIO_MAX = 5000
AUTHORS_PATTERN = "authors:*"


def _redis():
    return current_app.extensions["redis"]


def _ttl():
    return current_app.extensions["settings"].security.cache_ttl_seconds


def _public(row):
    return {k: row[k] for k in ("author_id", "first_name", "last_name", "biography", "books_count",
                                "created_at", "updated_at")}


def _invalidate():
    """Caché OPCIONAL: si Redis falla no se rompe la escritura ya hecha (la clave expirará por su TTL)."""
    _redis().cache_delete_pattern(AUTHORS_PATTERN)
    invalidate_all_books(_redis())


def _text(data, key, label, problems, required, maximum):
    if key not in data or data[key] is None:
        if required:
            problems.append({"field": key, "message": f"El campo {label} es obligatorio"})
        return None
    value = data[key]
    if not isinstance(value, str) or (required and not value.strip()):
        problems.append({"field": key, "message": f"El campo {label} debe ser texto" + (" no vacío" if required else "")})
    elif len(value.strip()) > maximum:
        problems.append({"field": key, "message": f"El campo {label} admite máximo {maximum} caracteres"})
    else:
        return value.strip()
    return None


def _author_fields(data, *, replace):
    problems = []
    unknown = [k for k in data if k not in ("first_name", "last_name", "biography")]
    if unknown:
        problems.append({"field": ", ".join(unknown), "message": "Campo no permitido"})
    first = _text(data, "first_name", "first_name", problems, required=replace or "first_name" in data, maximum=NAME_MAX)
    last = _text(data, "last_name", "last_name", problems, required=False, maximum=NAME_MAX)
    bio = _text(data, "biography", "biography", problems, required=False, maximum=BIO_MAX)
    if not replace and not any(k in data for k in ("first_name", "last_name", "biography")):
        problems.append({"field": "", "message": "Envía al menos un campo para modificar"})
    if problems:
        raise ApiError("validation_error", "Los datos enviados no son válidos", 400, problems)
    return first, last, bio


def register_routes(app, jwt_auth, repo):
    write = jwt_auth.required(roles=(ROLE_ADMIN, ROLE_STAFF))

    def must_exist(author_id):
        author = repo.get(author_id)
        if author is None:
            raise ApiError("not_found", f"No existe el autor {author_id}", 404)
        return author

    @app.get("/authors")
    def list_authors():
        limit, offset = page_args()
        key = f"authors:list:{limit}" if offset == 0 else None  # solo la primera página se cachea (claves acotadas)
        payload = _redis().cache_get(key) if key else None
        if payload is None:
            payload = {"authors": [_public(a) for a in repo.list(limit, offset)], "limit": limit, "offset": offset}
            if key:
                _redis().cache_set(key, payload, _ttl())
        return render(payload)

    @app.get("/authors/<int:author_id>")
    def get_author(author_id):
        key = f"authors:{author_id}"
        payload = _redis().cache_get(key)
        if payload is None:
            payload = {"author": _public(must_exist(author_id))}
            _redis().cache_set(key, payload, _ttl())
        return render(payload)

    @app.get("/authors/<int:author_id>/books")
    def author_books(author_id):
        must_exist(author_id)
        return render({"author_id": author_id, "books": repo.books(author_id)})

    @app.post("/authors")
    @write
    def create_author():
        first, last, bio = _author_fields(json_body(), replace=True)
        author_id = repo.create(first, last, bio)
        _invalidate()
        return render({"message": "Autor creado.", "author": _public(must_exist(author_id))}, 201)

    def update(author_id, replace):
        first, last, bio = _author_fields(json_body(), replace=replace)
        repo.update(author_id, first, last, bio, replace)
        _invalidate()
        return render({"message": "Autor actualizado.", "author": _public(must_exist(author_id))})

    @app.put("/authors/<int:author_id>")
    @write
    def put_author(author_id):
        return update(author_id, replace=True)

    @app.patch("/authors/<int:author_id>")
    @write
    def patch_author(author_id):
        return update(author_id, replace=False)

    @app.delete("/authors/<int:author_id>")
    @write
    def delete_author(author_id):
        must_exist(author_id)
        repo.delete(author_id)  # 409 reference_conflict si todavía tiene libros vinculados
        _invalidate()
        return render({"message": "Autor eliminado."})

    @app.post("/authors/<int:author_id>/books")
    @write
    def link_book(author_id):
        data = json_body()
        isbn = data.get("isbn")
        order = data.get("author_order")
        if not isinstance(isbn, str) or not isbn.strip() or len(isbn.strip()) > 17:
            raise ApiError("validation_error", "isbn es obligatorio (texto de hasta 17 caracteres)", 400,
                           [{"field": "isbn", "message": "Obligatorio"}])
        if order is not None and (isinstance(order, bool) or not isinstance(order, int) or not 1 <= order <= 99):
            raise ApiError("validation_error", "author_order debe ser un entero entre 1 y 99", 400,
                           [{"field": "author_order", "message": "Entero entre 1 y 99"}])
        repo.link_book(author_id, isbn.strip(), order)
        _invalidate()
        return render({"message": "Autor vinculado al libro.", "author": _public(must_exist(author_id))}, 201)

    @app.delete("/authors/<int:author_id>/books/<isbn>")
    @write
    def unlink_book(author_id, isbn):
        repo.unlink_book(author_id, isbn)
        _invalidate()
        return render({"message": "Vínculo eliminado."})
