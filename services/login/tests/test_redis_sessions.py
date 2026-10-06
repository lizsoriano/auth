"""Sesión, refresh token y revocación de JWT en Redis (con fakeredis; el TTL de Redis usa el reloj real,
mientras que la lógica de caducidad de la app usa el FakeClock)."""
import hashlib
import json
import logging
from datetime import datetime, timezone

import jwt as pyjwt
import pytest
from library_common import issue_access_token

from conftest import JWT_SECRET


def js(r):
    return json.loads(r.get_data(as_text=True))


def login(client, person):
    return client.post("/login?format=json", json={"email": person["email"], "password": person["password"]})


def claims(token):
    return pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"verify_exp": False, "verify_iss": False})


def sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def refresh(client, token):
    return client.post("/token/refresh?format=json", json={"refresh_token": token})


@pytest.fixture
def registered(client, good):
    assert client.post("/register?format=json", json=good).status_code == 201
    return good


# ------------------------------------------------------------------ login
def test_login_stores_session_and_refresh_in_redis_with_ttl(client, registered, redis_raw):
    body = js(login(client, registered))
    [session_key] = list(redis_raw.scan_iter("session:*"))
    assert 1700 < redis_raw.ttl(session_key) <= 1800
    data = json.loads(redis_raw.get(session_key))
    assert data["user_id"] == 1 and data["jti"] == claims(body["token"])["jti"]

    refresh_key = f"refresh:{sha(body['refresh_token'])}"
    assert redis_raw.exists(refresh_key) == 1 and 80000 < redis_raw.ttl(refresh_key) <= 86400
    assert data["refresh_hash"] == sha(body["refresh_token"])


def test_refresh_token_is_never_stored_in_clear(client, registered, redis_raw):
    body = js(login(client, registered))
    everything = " ".join(str(redis_raw.get(k)) + k for k in redis_raw.scan_iter("*"))
    assert body["refresh_token"] not in everything and body["token"] not in everything


def test_login_response_has_token_fields_in_xml_too(client, registered):
    r = client.post("/login", json={"email": registered["email"], "password": registered["password"]})
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert "<token>" in text and "<refresh_token>" in text and "<token_expires_in_seconds>1200<" in text


# ----------------------------------------------------------------- logout
def test_logout_revokes_the_jwt_and_deletes_session_and_refresh(client, registered, redis_raw, repo):
    body = login(client, registered)
    body = js(body)
    jti = claims(body["token"])["jti"]
    assert client.post("/logout?format=json").status_code == 200

    assert list(redis_raw.scan_iter("session:*")) == [] and list(redis_raw.scan_iter("refresh:*")) == []
    assert redis_raw.exists(f"jwt:revoked:{jti}") == 1 and 0 < redis_raw.ttl(f"jwt:revoked:{jti}") <= 1200
    assert next(iter(repo.sessions.values()))["revoked_at"] is not None


def test_relogin_ends_the_previous_session_jwt_and_refresh(client, registered, redis_raw):
    first = js(login(client, registered))
    second = js(login(client, registered))
    assert redis_raw.exists(f"jwt:revoked:{claims(first['token'])['jti']}") == 1
    assert redis_raw.exists(f"jwt:revoked:{claims(second['token'])['jti']}") == 0
    assert redis_raw.exists(f"refresh:{sha(first['refresh_token'])}") == 0
    assert len(list(redis_raw.scan_iter("session:*"))) == 1


def test_expired_session_logout_still_cleans_up(client, registered, redis_raw, clock):
    login(client, registered)
    clock.advance(minutes=31)
    r = client.post("/logout?format=json")
    assert r.status_code == 401 and js(r)["error"]["code"] == "session_expired"
    assert list(redis_raw.scan_iter("refresh:*")) == [] and list(redis_raw.scan_iter("session:*")) == []


# -------------------------------------------------------------- refresh
def test_refresh_rotates_tokens_and_revokes_the_old_jwt(client, registered, redis_raw, clock):
    first = js(login(client, registered))
    old_jti = claims(first["token"])["jti"]
    clock.advance(minutes=15)

    r = refresh(client, first["refresh_token"])
    assert r.status_code == 200
    new = js(r)
    assert new["token"] != first["token"] and new["refresh_token"] != first["refresh_token"]
    new_claims = claims(new["token"])
    assert new_claims["jti"] != old_jti and new_claims["exp"] - new_claims["iat"] == 1200 and new_claims["user_id"] == 1
    assert new["token_expires_in_seconds"] == 1200 and new["session"]["expires_in_seconds"] == 1800

    assert redis_raw.exists(f"jwt:revoked:{old_jti}") == 1
    assert redis_raw.exists(f"jwt:revoked:{new_claims['jti']}") == 0
    assert redis_raw.exists(f"refresh:{sha(first['refresh_token'])}") == 0
    assert redis_raw.exists(f"refresh:{sha(new['refresh_token'])}") == 1
    # la sesión también se renovó: 30 min desde el refresh
    assert js(client.get("/session?format=json"))["session"]["expires_in_seconds"] == 1800


def test_a_refresh_token_works_only_once(client, registered):
    first = js(login(client, registered))
    assert refresh(client, first["refresh_token"]).status_code == 200
    again = refresh(client, first["refresh_token"])
    assert again.status_code == 401 and js(again)["error"]["code"] == "invalid_refresh_token"


def test_the_new_refresh_token_can_be_chained(client, registered):
    token = js(login(client, registered))["refresh_token"]
    for _ in range(3):
        r = refresh(client, token)
        assert r.status_code == 200
        token = js(r)["refresh_token"]


def test_refresh_after_the_jwt_already_expired_does_not_need_to_revoke_it(client, registered, redis_raw, clock):
    first = js(login(client, registered))
    clock.advance(minutes=25)  # el JWT (20 min) ya expiró; la sesión (30 min) sigue viva
    assert refresh(client, first["refresh_token"]).status_code == 200
    assert redis_raw.exists(f"jwt:revoked:{claims(first['token'])['jti']}") == 0


@pytest.mark.parametrize("body", [{}, {"refresh_token": ""}, {"refresh_token": "corto"}, {"refresh_token": 123},
                                  {"refresh_token": "x" * 43}])
def test_refresh_rejects_missing_malformed_or_unknown_tokens(client, registered, body):
    login(client, registered)
    r = client.post("/token/refresh?format=json", json=body)
    assert r.status_code == 401 and js(r)["error"]["code"] == "invalid_refresh_token"


def test_refresh_needs_a_json_object_body(client, registered):
    assert client.post("/token/refresh?format=json", data="no es json").status_code == 400


def test_refresh_after_logout_is_rejected(client, registered):
    first = js(login(client, registered))
    client.post("/logout?format=json")
    r = refresh(client, first["refresh_token"])
    assert r.status_code == 401 and js(r)["error"]["code"] == "invalid_refresh_token"


def test_refresh_after_the_session_expired_is_rejected(client, registered, clock):
    first = js(login(client, registered))
    clock.advance(minutes=31)
    assert refresh(client, first["refresh_token"]).status_code == 401


def test_refresh_picks_up_a_role_change(client, repo, registered, clock):
    clock.now = datetime.now(timezone.utc)
    first = js(login(client, registered))
    assert claims(first["token"])["role_id"] == 3
    repo.users[registered["email"]]["role_id"] = 2
    assert claims(js(refresh(client, first["refresh_token"]))["token"])["role_id"] == 2


def test_refresh_for_a_disabled_account_is_403_and_closes_the_session(client, repo, registered, redis_raw):
    first = js(login(client, registered))
    repo.users[registered["email"]]["is_active"] = False
    r = refresh(client, first["refresh_token"])
    assert r.status_code == 403 and js(r)["error"]["code"] == "account_disabled"
    assert list(redis_raw.scan_iter("session:*")) == [] and list(redis_raw.scan_iter("refresh:*")) == []


def test_session_has_an_absolute_lifetime_even_if_kept_alive_with_refresh(client, registered, clock):
    tokens = js(login(client, registered))
    for step in range(1, 70):
        clock.advance(minutes=25)
        r = refresh(client, tokens["refresh_token"])
        if r.status_code == 401:
            break
        tokens = js(r)
    assert r.status_code == 401
    assert step * 25 >= 24 * 60 > (step - 1) * 25  # corta justo al cumplirse REFRESH_TOKEN_TTL_HOURS (24 h)


# ------------------------------------------------------------- sesión / extend
def test_session_extend_renews_redis_window_and_ttl(client, registered, redis_raw, clock):
    login(client, registered)
    clock.advance(minutes=20)
    assert js(client.get("/session?format=json"))["session"]["expires_in_seconds"] == 600
    r = client.post("/session/extend?format=json")
    assert r.status_code == 200 and js(r)["session"]["expires_in_seconds"] == 1800
    assert js(client.get("/session?format=json"))["session"]["expires_in_seconds"] == 1800
    [key] = list(redis_raw.scan_iter("session:*"))
    assert redis_raw.ttl(key) > 1700


def test_session_extend_without_session_is_401(client):
    assert js(client.post("/session/extend?format=json"))["error"]["code"] == "not_authenticated"


def test_session_reports_expired_when_the_redis_key_vanishes(client, registered, redis_raw):
    login(client, registered)
    for key in redis_raw.scan_iter("session:*"):
        redis_raw.delete(key)  # lo que hace Redis al vencer el TTL
    r = client.get("/session?format=json")
    assert r.status_code == 401 and js(r)["error"]["code"] == "session_expired"


def test_profile_update_works_with_the_redis_session(client, registered):
    login(client, registered)
    r = client.patch("/profile?format=json", json={"nombre": "Ana María"})
    assert r.status_code == 200 and js(r)["user"]["nombre"] == "Ana María"
    assert js(r)["user"]["display_name"].startswith("Ana María")


def test_profile_requires_a_session(client):
    assert client.patch("/profile?format=json", json={"nombre": "X"}).status_code == 401


# ------------------------------------------------------------- Redis caído
def test_redis_down_denies_everything_that_needs_it_and_does_not_leave_a_live_session(
        client, registered, redis_server, repo):
    redis_server.connected = False
    r = login(client, registered)
    body = js(r)
    assert r.status_code == 503 and body["error"]["code"] == "redis_unavailable"
    assert "token" not in body and "refresh_token" not in body
    assert all(s["revoked_at"] is not None for s in repo.sessions.values())  # sin Redis no queda sesión viva
    assert client.get_cookie("login_session") is None
    assert js(client.get("/health?format=json"))["error"]["code"] == "redis_unavailable"
    redis_server.connected = True


def test_redis_down_after_login_denies_session_logout_refresh_and_extend(client, registered, redis_server):
    first = js(login(client, registered))
    redis_server.connected = False
    assert client.get("/session?format=json").status_code == 503
    assert client.post("/session/extend?format=json").status_code == 503
    assert client.post("/logout?format=json").status_code == 503
    r = refresh(client, first["refresh_token"])
    assert r.status_code == 503 and js(r)["error"]["code"] == "redis_unavailable"
    redis_server.connected = True
    # al volver Redis, la sesión sigue ahí: el logout fallido no cerró nada a medias
    assert client.get("/session?format=json").status_code == 200


def test_register_does_not_need_redis(client, good, redis_down):
    assert client.post("/register?format=json", json=good).status_code == 201


# ------------------------------------------------------- métricas y logs
def _admin_token(role_id):
    return issue_access_token(secret_key=JWT_SECRET, issuer="library-login", user_id=99, role_id=role_id,
                              now=datetime.now(timezone.utc), ttl_minutes=20)[0]


def test_metrics_endpoint_requires_an_admin_jwt(client):
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": f"Bearer {_admin_token(3)}"}).status_code == 403
    r = client.get("/metrics", headers={"Authorization": f"Bearer {_admin_token(1)}"})
    assert r.status_code == 200 and 'service="login"' in r.get_data(as_text=True)


def test_a_revoked_admin_token_cannot_read_metrics(client, redis_layer):
    token = _admin_token(1)
    redis_layer.revoke_jti(pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer="library-login")["jti"], 600)
    assert client.get("/metrics", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_tokens_and_passwords_never_reach_the_logs(client, registered, caplog):
    caplog.set_level(logging.DEBUG)
    body = js(login(client, registered))
    new = js(refresh(client, body["refresh_token"]))
    client.post("/logout?format=json")
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (body["token"], body["refresh_token"], new["token"], new["refresh_token"], registered["password"]):
        assert secret not in log_text
