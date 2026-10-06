import sys
from pathlib import Path

import fakeredis
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "shared"))  # library_common (paquete compartido)

from library_common import Metrics, RedisLayer, SecuritySettings, ServiceSettings  # noqa: E402
from library_common.testing import SECRET, admin_conn, database_url, unique  # noqa: E402
from users_service import create_app  # noqa: E402


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
    return Metrics("users")


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
def make_user():
    """Crea usuarios directamente en la BD (rol y contraseña conocidos) y los borra al terminar."""
    from library_common import passwords
    created = []

    def _make(role_id=3, password="ClaveSegura123", active=True):
        email = f"{unique('u')}@example.com"
        with admin_conn() as conn:
            row = conn.execute(
                "INSERT INTO users (email, password_hash, display_name, role_id, is_active) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING user_id",
                (email, passwords.hash_password(password, 4), "Usuario de prueba", role_id, active)).fetchone()
        created.append(row[0])
        return {"user_id": row[0], "email": email, "password": password, "role_id": role_id}

    yield _make
    with admin_conn() as conn:
        for user_id in created:
            conn.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
