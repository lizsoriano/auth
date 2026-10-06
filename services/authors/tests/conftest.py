import sys
from pathlib import Path

import fakeredis
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "shared"))  # library_common (paquete compartido)

from library_common import Metrics, RedisLayer, SecuritySettings, ServiceSettings  # noqa: E402
from library_common.testing import SECRET, admin_conn, database_url, unique  # noqa: E402
from authors_service import create_app  # noqa: E402


@pytest.fixture
def redis_server():
    return fakeredis.FakeServer()


@pytest.fixture
def raw(redis_server):
    return fakeredis.FakeRedis(server=redis_server, decode_responses=True)


@pytest.fixture
def redis_down(redis_server):
    redis_server.connected = False
    yield
    redis_server.connected = True


@pytest.fixture
def metrics():
    return Metrics("authors")


@pytest.fixture
def layer(redis_server, metrics):
    return RedisLayer(fakeredis.FakeRedis(server=redis_server, decode_responses=True), metrics)


@pytest.fixture
def app(layer, metrics):
    settings = ServiceSettings(database_url=database_url(), bcrypt_rounds=4,
                               security=SecuritySettings(jwt_secret_key=SECRET))
    return create_app(settings, redis_layer=layer, metrics=metrics)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_book():
    """Crea libros de prueba (ISBN único de 13 dígitos) con la conexión del dueño y los borra al terminar."""
    import random
    created = []

    def _make(title="Libro de prueba"):
        isbn = "978" + "".join(random.choice("0123456789") for _ in range(10))
        with admin_conn() as conn:
            fmt = conn.execute("SELECT format_id FROM formats ORDER BY 1 LIMIT 1").fetchone()[0]
            cat = conn.execute("SELECT category_id FROM categories ORDER BY 1 LIMIT 1").fetchone()[0]
            book_id = conn.execute(
                "INSERT INTO books (isbn, title, publication_year, price, stock, format_id, category_id) "
                "VALUES (%s, %s, 2020, 100, 5, %s, %s) RETURNING book_id", (isbn, title, fmt, cat)).fetchone()[0]
        created.append(book_id)
        return {"book_id": book_id, "isbn": isbn, "title": title}

    yield _make
    with admin_conn() as conn:
        for book_id in created:
            conn.execute("DELETE FROM books WHERE book_id = %s", (book_id,))


@pytest.fixture
def make_author():
    """Crea autores directamente en la BD y los borra al terminar (después de desvincularlos)."""
    created = []

    def _make(first="Autor", last="De Prueba"):
        with admin_conn() as conn:
            author_id = conn.execute("INSERT INTO authors (first_name, last_name) VALUES (%s, %s) RETURNING author_id",
                                     (f"{first} {unique('a')}", last)).fetchone()[0]
        created.append(author_id)
        return author_id

    yield _make
    with admin_conn() as conn:
        for author_id in created:
            conn.execute("DELETE FROM book_authors WHERE author_id = %s", (author_id,))
            conn.execute("DELETE FROM authors WHERE author_id = %s", (author_id,))
