"""JWT emitido por POST /login: HS256, 20 minutos, claims user_id/role_id/jti (lo validan los 6 servicios)."""
import json
from datetime import datetime, timezone

import jwt as pyjwt
import pytest
from library_common import decode_access_token

from conftest import JWT_SECRET


def js(r):
    return json.loads(r.get_data(as_text=True))


def login_body(client, person):
    return js(client.post("/login?format=json", json={"email": person["email"], "password": person["password"]}))


@pytest.fixture
def registered(client, good):
    assert client.post("/register?format=json", json=good).status_code == 201
    return good


def test_login_returns_a_valid_jwt_with_the_required_claims(client, registered, clock):
    # PyJWT valida "exp" contra el reloj real del sistema (no es inyectable): se ancla el FakeClock a "ahora".
    clock.now = datetime.now(timezone.utc)
    body = login_body(client, registered)
    token = body["token"]
    assert token.count(".") == 2 and body["token_type"] == "Bearer" and body["token_expires_in_seconds"] == 1200

    payload = decode_access_token(token, secret_key=JWT_SECRET, issuer="library-login")
    assert payload["user_id"] == 1 and payload["sub"] == "1"
    assert payload["role_id"] == 3 and payload["role"] == "customer"
    assert payload["iss"] == "library-login"
    assert payload["exp"] - payload["iat"] == 20 * 60
    assert len(payload["jti"]) >= 16


def test_jwt_uses_hs256_and_rejects_other_secret(client, registered):
    token = login_body(client, registered)["token"]
    assert pyjwt.get_unverified_header(token)["alg"] == "HS256"
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, "una-clave-distinta-0123456789abcdef", algorithms=["HS256"], options={"verify_exp": False})


def test_every_login_gets_a_different_jti(client, registered):
    jtis = {pyjwt.decode(login_body(client, registered)["token"], JWT_SECRET, algorithms=["HS256"],
                         options={"verify_exp": False, "verify_iss": False})["jti"] for _ in range(3)}
    assert len(jtis) == 3


@pytest.mark.parametrize("role_id,name", [(1, "admin"), (2, "staff"), (3, "customer")])
def test_jwt_role_id_comes_from_the_users_role(client, repo, good, clock, role_id, name):
    clock.now = datetime.now(timezone.utc)
    client.post("/register?format=json", json=good)
    repo.users[good["email"]]["role_id"] = role_id
    body = login_body(client, good)
    payload = decode_access_token(body["token"], secret_key=JWT_SECRET, issuer="library-login")
    assert payload["role_id"] == role_id and payload["role"] == name
    assert body["user"]["role_id"] == role_id and body["user"]["role"] == name


def test_wrong_password_returns_401_without_tokens(client, registered):
    r = client.post("/login?format=json", json={"email": registered["email"], "password": "incorrecta"})
    body = js(r)
    assert r.status_code == 401
    assert "token" not in body and "refresh_token" not in body


def test_settings_requires_a_strong_jwt_secret():
    from login_service import Settings
    with pytest.raises(Exception, match="JWT_SECRET_KEY"):
        Settings(secret_key="x" * 20, database_url="postgresql://x", jwt_secret_key="", redis_url="redis://x").validate()
    with pytest.raises(Exception, match="JWT_SECRET_KEY"):
        Settings(secret_key="x" * 20, database_url="postgresql://x", jwt_secret_key="corta", redis_url="redis://x").validate()


def test_settings_requires_redis_url_unless_injected():
    from login_service import Settings
    ok = dict(secret_key="x" * 20, database_url="postgresql://x", jwt_secret_key=JWT_SECRET, email_confirmation_required=False)
    with pytest.raises(Exception, match="REDIS_URL"):
        Settings(**ok).validate()
    Settings(**ok).validate(needs_redis=False)  # create_app(redis_layer=...) no necesita la URL
    Settings(**ok, redis_url="redis://:pw@127.0.0.1:6379/0").validate()
