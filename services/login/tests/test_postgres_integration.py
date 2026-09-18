"""Pruebas contra PostgreSQL REAL. Se omiten si no hay TEST_DATABASE_URL.

Preparación (BD desechable, NUNCA la de producción):
  1. psql -f data/schema.sql  (o el schema base + data/migrations/000..003)
  2. export TEST_DATABASE_URL=postgresql://login_service_user:...@host/library_db
     export TEST_ADMIN_DATABASE_URL=postgresql://library_user:...@host/library_db   # dueño; solo para forzar caducidades
  3. pytest tests/test_postgres_integration.py

El correo NO sale por Postfix aquí: se captura el enlace con un mailer de prueba.
Usan correos con sufijo aleatorio; no borran nada (el rol no tiene DELETE).
"""
import json
import os
import uuid

import pytest

DSN = os.getenv("TEST_DATABASE_URL")
ADMIN_DSN = os.getenv("TEST_ADMIN_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL no configurada")


class CaptureMailer:
    def __init__(self):
        self.sent = []

    def send_verification(self, to_email, nombre, link, ttl_hours):
        self.sent.append((to_email, link))

    @property
    def token(self):
        return self.sent[-1][1].rsplit("/", 1)[1]


@pytest.fixture
def mailer():
    return CaptureMailer()


@pytest.fixture
def pg_client(mailer):
    from login_service import Settings, create_app
    settings = Settings(secret_key="integration-secret-0123456789", database_url=DSN, bcrypt_rounds=4,
                        mail_from="Library <no-reply@example.com>", email_confirmation_required=True)
    return create_app(settings, mailer=mailer).test_client()


@pytest.fixture
def person():
    return {"nombre": "Ana", "apellido_paterno": "López", "apellido_materno": "Díaz",
            "email": f"it-{uuid.uuid4().hex[:10]}@gmail.com", "password": "ClaveSegura123"}


def js(r):
    return json.loads(r.get_data(as_text=True))


def admin_select(sql, params=()):
    import psycopg
    if not ADMIN_DSN:
        pytest.skip("TEST_ADMIN_DATABASE_URL no configurada (dueño de las tablas)")
    with psycopg.connect(ADMIN_DSN) as conn:
        return conn.execute(sql, params).fetchall()


def admin_update(sql, params=()):
    import psycopg
    if not ADMIN_DSN:
        pytest.skip("TEST_ADMIN_DATABASE_URL no configurada (dueño de las tablas)")
    with psycopg.connect(ADMIN_DSN) as conn:
        conn.execute(sql, params)


def test_health_sees_database_and_schema(pg_client):
    r = pg_client.get("/health?format=json")
    assert r.status_code == 200 and js(r)["schema"] == "ok"


def test_full_flow_with_email_confirmation_against_postgres(pg_client, person, mailer):
    r = pg_client.post("/register?format=json", json=person)
    assert r.status_code == 201 and js(r)["verification_email"] == "sent" and js(r)["user"]["email_verified"] is False
    assert pg_client.post("/register?format=json", json=dict(person, email=person["email"].upper())).status_code == 409
    login = {"email": person["email"], "password": person["password"]}
    assert pg_client.post("/login?format=json", json={"email": person["email"], "password": "mala"}).status_code == 401
    blocked = pg_client.post("/login?format=json", json=login)
    assert blocked.status_code == 403 and js(blocked)["error"]["code"] == "email_not_confirmed"

    assert pg_client.get(f"/verify/{mailer.token}?format=json").status_code == 200
    assert js(pg_client.get(f"/verify/{mailer.token}?format=json"))["status"] == "already_confirmed"
    ok = pg_client.post("/login?format=json", json=login)
    assert ok.status_code == 200 and js(ok)["user"]["display_name"] == "Ana López Díaz"
    s = pg_client.get("/session?format=json")
    assert s.status_code == 200 and 0 < js(s)["session"]["expires_in_seconds"] <= 1800
    assert pg_client.post("/logout?format=json").status_code == 200
    assert pg_client.get("/session?format=json").status_code == 401


def test_token_is_stored_hashed_and_expired_token_is_410(pg_client, person, mailer):
    pg_client.post("/register?format=json", json=person)
    rows = admin_select("select v.token_hash, v.used_at from email_verifications v join users u using (user_id) "
                        "where u.email = %s", (person["email"],))
    assert len(rows) == 1 and rows[0][0] != mailer.token and len(rows[0][0]) == 64 and rows[0][1] is None
    admin_update("update email_verifications set created_at = now() - interval '25 hours', "
                 "expires_at = now() - interval '1 hour' where user_id = (select user_id from users where email = %s)",
                 (person["email"],))
    r = pg_client.get(f"/verify/{mailer.token}?format=json")
    assert r.status_code == 410 and js(r)["error"]["code"] == "token_expired"
    # el enfriamiento ya pasó (el token viejo es de hace 25 h): un reenvío permite confirmar
    assert pg_client.post("/resend-verification?format=json", json={"email": person["email"]}).status_code == 202
    assert pg_client.get(f"/verify/{mailer.token}?format=json").status_code == 200


def test_expired_session_reported_from_postgres(pg_client, person, mailer):
    pg_client.post("/register?format=json", json=person)
    pg_client.get(f"/verify/{mailer.token}?format=json")
    pg_client.post("/login?format=json", json={"email": person["email"], "password": person["password"]})
    admin_update("update login_sessions set created_at = now() - interval '31 minutes', "
                 "expires_at = now() - interval '1 minute' where user_id = (select user_id from users where email = %s)",
                 (person["email"],))
    r = pg_client.get("/session?format=json")
    assert r.status_code == 401 and js(r)["error"]["code"] == "session_expired"
