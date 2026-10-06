"""Ayudas para las pruebas de los microservicios (no se usan en producción).

Las pruebas de Users, Authors, Pedidos y Pagos corren contra un PostgreSQL REAL con las migraciones 006-011 y
Redis simulado (fakeredis). Variables: TEST_DATABASE_URL (rol de ESE servicio) y TEST_ADMIN_DATABASE_URL
(library_user, solo para preparar y limpiar datos). Si falta TEST_DATABASE_URL las pruebas se omiten.
"""
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from .jwt_auth import issue_access_token

SECRET = "test-jwt-secret-key-0123456789abcdef"  # 36 caracteres (mínimo 32)
ISSUER = "library-login"


def token_for(role_id, user_id=1, *, secret=SECRET, issuer=ISSUER, now=None):
    return issue_access_token(secret_key=secret, issuer=issuer, user_id=user_id, role_id=role_id,
                              now=now or datetime.now(timezone.utc), ttl_minutes=20)


def bearer(role_id, user_id=1, **kwargs):
    return {"Authorization": f"Bearer {token_for(role_id, user_id, **kwargs)[0]}"}


def database_url():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no configurada (PostgreSQL de pruebas con las migraciones 006-011)")
    return url


@contextmanager
def admin_conn():
    """Conexión de library_user (dueño) para preparar/limpiar datos de prueba; autocommit."""
    import psycopg
    url = os.getenv("TEST_ADMIN_DATABASE_URL")
    if not url:
        pytest.skip("TEST_ADMIN_DATABASE_URL no configurada (dueño de las tablas)")
    with psycopg.connect(url, autocommit=True) as conn:
        yield conn


def unique(prefix="t"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"
