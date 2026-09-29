"""JWT emitido por POST /login (lo valida services/soap en sus escrituras)."""
import json
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest

JWT_SECRET = "test-jwt-secret-0123456789"


def js(r):
    return json.loads(r.get_data(as_text=True))


@pytest.fixture
def registered(client, good):
    assert client.post("/register?format=json", json=good).status_code == 201
    return good


def test_login_returns_a_valid_jwt(client, registered, clock):
    # PyJWT valida "exp" contra el reloj real del sistema (no es inyectable),
    # así que se ancla el FakeClock a "ahora" real para que el token recién
    # emitido no nazca ya "expirado" según ese reloj real.
    clock.now = datetime.now(timezone.utc)
    body = js(client.post("/login?format=json", json={"email": registered["email"], "password": registered["password"]}))
    token = body["token"]
    assert isinstance(token, str) and token.count(".") == 2  # header.payload.signature

    payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    assert payload["sub"] == "1"
    assert payload["role"] == "user"
    assert payload["exp"] - payload["iat"] == 2 * 3600  # JWT_EXPIRATION_HOURS por defecto en el fixture


def test_login_jwt_uses_hs256_and_rejects_other_secret(client, registered):
    token = js(client.post("/login?format=json", json={"email": registered["email"], "password": registered["password"]}))["token"]
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "HS256"
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, "una-clave-distinta-0123456789", algorithms=["HS256"])


def test_login_jwt_role_reflects_is_admin(client, repo, good, clock):
    clock.now = datetime.now(timezone.utc)
    client.post("/register?format=json", json=good)
    repo.users[good["email"]]["is_admin"] = True
    body = js(client.post("/login?format=json", json={"email": good["email"], "password": good["password"]}))
    payload = pyjwt.decode(body["token"], JWT_SECRET, algorithms=["HS256"])
    assert payload["role"] == "admin"


def test_wrong_password_returns_401_without_token(client, registered):
    r = client.post("/login?format=json", json={"email": registered["email"], "password": "incorrecta"})
    body = js(r)
    assert r.status_code == 401
    assert "token" not in body and "token" not in body.get("error", {})


def test_jwt_expires_after_configured_hours(client, registered, clock):
    """PyJWT compara "exp" contra el reloj REAL del proceso, no contra el
    FakeClock de la app -- avanzar el FakeClock y re-decodificar el MISMO
    token no tendría ningún efecto. En su lugar se emite un token cuyo
    `iat` ya queda, en el reloj real, más allá de JWT_EXPIRATION_HOURS: es
    exactamente lo que ocurre en producción cuando de verdad pasan 2 horas."""
    clock.now = datetime.now(timezone.utc)
    vigente = js(client.post("/login?format=json", json={"email": registered["email"], "password": registered["password"]}))["token"]
    pyjwt.decode(vigente, JWT_SECRET, algorithms=["HS256"])  # aun valido

    clock.now = datetime.now(timezone.utc) - timedelta(hours=2, seconds=1)
    expirado = js(client.post("/login?format=json", json={"email": registered["email"], "password": registered["password"]}))["token"]
    with pytest.raises(pyjwt.ExpiredSignatureError):
        pyjwt.decode(expirado, JWT_SECRET, algorithms=["HS256"])


def test_settings_requires_jwt_secret():
    from login_service import Settings
    with pytest.raises(Exception, match="JWT_SECRET"):
        Settings(secret_key="x" * 20, database_url="postgresql://x", jwt_secret="").validate()
