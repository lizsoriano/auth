import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import fakeredis
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "shared"))  # library_common (paquete compartido)

import rest_api  # noqa: E402
from app import create_app  # noqa: E402
from db.errors import LibroInvalidoError, LibroNoEncontradoError  # noqa: E402
from library_common import Metrics, RedisLayer, SecuritySettings, issue_access_token  # noqa: E402

JWT_SECRET = "test-jwt-secret-key-0123456789abcdef"  # 36 caracteres
ISSUER = "library-login"


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchone(self):
        return (1,)


class FakeConn:
    def cursor(self):
        return FakeCursor()

    def commit(self):
        pass


class FakeDb:
    """Reemplaza db.repository/db.connection: guarda los libros en memoria y cuenta las consultas a "PostgreSQL"."""

    def __init__(self):
        self.books = [
            dict(book_id=1, isbn="9780000000006", title="1984", price=Decimal("219.00"), category="Ficcion",
                 stock=20, publication_year=1949, authors="George Orwell"),
            dict(book_id=2, isbn="9780000000001", title="Cien anos de soledad", price=Decimal("349.00"),
                 category="Ficcion", stock=12, publication_year=1967, authors="Gabriel Garcia Marquez"),
        ]
        self.list_calls = 0
        self.write_calls = 0
        self.down = False

    @contextmanager
    def connection(self):
        if self.down:
            raise RuntimeError("postgres caído")
        yield FakeConn()

    def listar_libros(self, conn):
        self.list_calls += 1
        return [dict(b) for b in sorted(self.books, key=lambda b: b["title"])]

    def listar_libros_con_imagenes(self, conn):
        return [{"book_id": b["book_id"], "isbn": b["isbn"], "title": b["title"],
                 "images": [{"url": f"/uploads/seed/{b['isbn']}-1.jpg", "is_cover": True}]} for b in self.books]

    def crear_libro(self, conn, *, isbn, title, publication_year, price, stock, category, format, authors):
        self.write_calls += 1
        if any(b["isbn"] == isbn for b in self.books):
            raise LibroInvalidoError("Ya existe un libro con ese ISBN")
        book_id = max(b["book_id"] for b in self.books) + 1
        self.books.append(dict(book_id=book_id, isbn=isbn, title=title, price=Decimal(str(price)), category=category,
                               stock=stock, publication_year=publication_year, authors=authors))
        return book_id

    def actualizar_libro(self, conn, *, isbn, title, publication_year, price, stock, category, format, authors):
        self.write_calls += 1
        book = next((b for b in self.books if b["isbn"] == isbn), None)
        if book is None:
            raise LibroNoEncontradoError(f"No existe un libro con isbn {isbn}")
        new = dict(title=title, publication_year=publication_year, price=price, stock=stock, category=category,
                   authors=authors)
        book.update({k: (Decimal(str(v)) if k == "price" and v is not None else v)
                     for k, v in new.items() if v is not None})

    def eliminar_libro(self, conn, isbn):
        self.write_calls += 1
        before = len(self.books)
        self.books = [b for b in self.books if b["isbn"] != isbn]
        if len(self.books) == before:
            raise LibroNoEncontradoError(f"No existe un libro con isbn {isbn}")


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(rest_api.connection, "get_connection", fake.connection)
    for name in ("listar_libros", "listar_libros_con_imagenes", "crear_libro", "actualizar_libro", "eliminar_libro"):
        monkeypatch.setattr(rest_api.repository, name, getattr(fake, name))
    return fake


@pytest.fixture
def redis_server():
    return fakeredis.FakeServer()


@pytest.fixture
def raw(redis_server):
    """Cliente directo al Redis falso para inspeccionar claves y TTL."""
    return fakeredis.FakeRedis(server=redis_server, decode_responses=True)


@pytest.fixture
def redis_down(redis_server):
    redis_server.connected = False
    yield
    redis_server.connected = True


@pytest.fixture
def metrics():
    return Metrics("books")


@pytest.fixture
def layer(redis_server, metrics):
    return RedisLayer(fakeredis.FakeRedis(server=redis_server, decode_responses=True), metrics)


def make_settings(**override):
    base = dict(jwt_secret_key=JWT_SECRET, jwt_issuer=ISSUER, cache_ttl_seconds=60)
    base.update(override)
    return SecuritySettings(**base)


@pytest.fixture
def app(db, layer, metrics):
    return create_app(make_settings(), redis_layer=layer, metrics=metrics)


@pytest.fixture
def client(app):
    return app.test_client()


def token_for(role_id, *, user_id=7, issuer=ISSUER, secret=JWT_SECRET, now=None):
    return issue_access_token(secret_key=secret, issuer=issuer, user_id=user_id, role_id=role_id,
                              now=now or datetime.now(timezone.utc), ttl_minutes=20)


def bearer(role_id=1, **kw):
    return {"Authorization": f"Bearer {token_for(role_id, **kw)[0]}"}
