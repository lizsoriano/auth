import random
import sys
from pathlib import Path

import fakeredis
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "shared"))  # library_common (paquete compartido)

from library_common import Metrics, RedisLayer, SecuritySettings, ServiceSettings  # noqa: E402
from library_common.testing import SECRET, admin_conn, database_url, unique  # noqa: E402
from pedidos_service import create_app  # noqa: E402


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
    return Metrics("pedidos")


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
def world():
    """Usuarios y libros de prueba. Al terminar borra, en orden, pagos, pedidos, usuarios y libros creados."""
    users, books = [], []

    class World:
        @staticmethod
        def user(role_id=3, active=True):
            with admin_conn() as conn:
                uid = conn.execute(
                    "INSERT INTO users (email, password_hash, display_name, role_id, is_active) "
                    "VALUES (%s, 'x', 'Usuario de prueba', %s, %s) RETURNING user_id",
                    (f"{unique('u')}@example.com", role_id, active)).fetchone()[0]
            users.append(uid)
            return uid

        @staticmethod
        def book(stock=10, price=100):
            isbn = "978" + "".join(random.choice("0123456789") for _ in range(10))
            with admin_conn() as conn:
                fmt = conn.execute("SELECT format_id FROM formats ORDER BY 1 LIMIT 1").fetchone()[0]
                cat = conn.execute("SELECT category_id FROM categories ORDER BY 1 LIMIT 1").fetchone()[0]
                book_id = conn.execute(
                    "INSERT INTO books (isbn, title, publication_year, price, stock, format_id, category_id) "
                    "VALUES (%s, %s, 2020, %s, %s, %s, %s) RETURNING book_id",
                    (isbn, f"Libro {unique('b')}", price, stock, fmt, cat)).fetchone()[0]
            books.append(book_id)
            return {"book_id": book_id, "isbn": isbn}

        @staticmethod
        def stock(isbn):
            with admin_conn() as conn:
                return conn.execute("SELECT stock FROM books WHERE isbn = %s", (isbn,)).fetchone()[0]

        @staticmethod
        def order_count(user_id):
            with admin_conn() as conn:
                return conn.execute("SELECT count(*) FROM orders WHERE user_id = %s", (user_id,)).fetchone()[0]

    yield World
    with admin_conn() as conn:
        conn.execute("DELETE FROM payments WHERE user_id = ANY(%s) OR order_id IN (SELECT order_id FROM orders WHERE user_id = ANY(%s))",
                     (users, users))
        conn.execute("DELETE FROM orders WHERE user_id = ANY(%s)", (users,))
        conn.execute("DELETE FROM users WHERE user_id = ANY(%s)", (users,))
        conn.execute("DELETE FROM books WHERE book_id = ANY(%s)", (books,))
