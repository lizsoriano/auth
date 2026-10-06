import pathlib
import sys

import fakeredis
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from library_common import Metrics, RedisLayer  # noqa: E402

SECRET = "test-secret-key-" + "k" * 24  # 40 caracteres
ISSUER = "library-login"


@pytest.fixture
def metrics():
    return Metrics("test")


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def layer(server, metrics):
    return RedisLayer(fakeredis.FakeRedis(server=server, decode_responses=True), metrics)


@pytest.fixture
def raw(server):
    """Cliente directo al mismo servidor falso, para inspeccionar claves y TTL."""
    return fakeredis.FakeRedis(server=server, decode_responses=True)


@pytest.fixture
def redis_down(server):
    """Simula que Redis dejó de responder (cada comando lanza ConnectionError)."""
    server.connected = False
    yield
    server.connected = True
