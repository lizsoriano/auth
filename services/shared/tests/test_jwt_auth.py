import logging
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from flask import Flask, g, jsonify

from library_common import (
    ROLE_ADMIN, ROLE_CUSTOMER, ROLE_STAFF, JwtAuth, decode_access_token, issue_access_token)
from library_common.jwt_auth import TokenExpired

from conftest import ISSUER, SECRET


def _now():
    return datetime.now(timezone.utc)


def _token(role_id=ROLE_CUSTOMER, user_id=7, now=None, secret=SECRET, issuer=ISSUER):
    token, claims = issue_access_token(
        secret_key=secret, issuer=issuer, user_id=user_id, role_id=role_id,
        now=now or _now(), ttl_minutes=20)
    return token, claims


@pytest.fixture
def app(layer, metrics):
    auth = JwtAuth(secret_key=SECRET, issuer=ISSUER, redis_layer=layer, metrics=metrics)
    app = Flask(__name__)
    app.calls = []

    @app.post("/protegido")
    @auth.required()
    def protegido():
        app.calls.append("protegido")
        return jsonify(user_id=g.jwt_claims["user_id"], jti=g.jwt_claims["jti"])

    @app.delete("/admin")
    @auth.required(roles=("admin",))
    def admin():
        app.calls.append("admin")
        return jsonify(ok=True)

    @app.patch("/gestion")
    @auth.required(roles=(ROLE_ADMIN, ROLE_STAFF))
    def gestion():
        return jsonify(ok=True)

    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _code(response):
    return response.get_json(force=True, silent=True) or {}


# ------------------------------------------------------------ emisión / forma
def test_el_token_dura_20_minutos_y_trae_los_claims_pedidos():
    token, claims = _token(role_id=ROLE_STAFF, user_id=42)
    assert claims["exp"] - claims["iat"] == 20 * 60
    decoded = decode_access_token(token, secret_key=SECRET, issuer=ISSUER)
    assert decoded["user_id"] == 42 and decoded["role_id"] == ROLE_STAFF
    assert decoded["role"] == "staff" and decoded["iss"] == ISSUER and len(decoded["jti"]) >= 16
    assert pyjwt.get_unverified_header(token)["alg"] == "HS256"


def test_cada_token_tiene_un_jti_distinto():
    assert _token()[1]["jti"] != _token()[1]["jti"]


def test_jwtauth_rechaza_clave_corta(layer):
    with pytest.raises(ValueError):
        JwtAuth(secret_key="corta", issuer=ISSUER, redis_layer=layer)


# --------------------------------------------------------------- 401: inválidos
def test_sin_cabecera_authorization_es_401(client, app):
    r = client.post("/protegido")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")
    assert b"token_missing" in r.data
    assert app.calls == []


@pytest.mark.parametrize("valor", ["Token abc", "Bearer", "Bearer   ", "abc"])
def test_formato_incorrecto_es_401(client, app, valor):
    assert client.post("/protegido", headers={"Authorization": valor}).status_code == 401
    assert app.calls == []


def test_token_valido_pasa_y_expone_claims(client, app):
    token, claims = _token(user_id=9)
    r = client.post("/protegido", headers=_bearer(token))
    assert r.status_code == 200
    assert r.get_json()["user_id"] == 9 and r.get_json()["jti"] == claims["jti"]
    assert app.calls == ["protegido"]


def test_token_expirado_es_401(client, app):
    token, _ = _token(now=_now() - timedelta(minutes=30))
    r = client.post("/protegido", headers=_bearer(token))
    assert r.status_code == 401 and b"token_expired" in r.data
    assert app.calls == []
    with pytest.raises(TokenExpired):
        decode_access_token(token, secret_key=SECRET, issuer=ISSUER)


def test_firma_con_otra_clave_es_401(client, app):
    token, _ = _token(secret="otra-clave-distinta-" + "z" * 24)
    assert client.post("/protegido", headers=_bearer(token)).status_code == 401
    assert app.calls == []


def test_algoritmo_none_es_401(client, app):
    _, claims = _token()
    token = pyjwt.encode(claims, None, algorithm="none")
    assert client.post("/protegido", headers=_bearer(token)).status_code == 401
    assert app.calls == []


def test_otro_algoritmo_hs512_es_401(client, app):
    _, claims = _token()
    token = pyjwt.encode(claims, SECRET, algorithm="HS512")
    assert client.post("/protegido", headers=_bearer(token)).status_code == 401
    assert app.calls == []


def test_emisor_distinto_es_401(client, app):
    token, _ = _token(issuer="otro-emisor")
    assert client.post("/protegido", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize("faltante", ["jti", "user_id", "role_id", "iat", "exp", "iss"])
def test_claim_obligatorio_ausente_es_401(client, app, faltante):
    _, claims = _token()
    claims.pop(faltante)
    token = pyjwt.encode(claims, SECRET, algorithm="HS256")
    assert client.post("/protegido", headers=_bearer(token)).status_code == 401
    assert app.calls == []


def test_user_id_no_numerico_es_401(client):
    _, claims = _token()
    claims["user_id"] = "7"
    token = pyjwt.encode(claims, SECRET, algorithm="HS256")
    assert client.post("/protegido", headers=_bearer(token)).status_code == 401


# ------------------------------------------------------------------ revocación
def test_token_revocado_es_401(client, app, layer):
    token, claims = _token()
    assert client.post("/protegido", headers=_bearer(token)).status_code == 200
    layer.revoke_jti(claims["jti"], 600)
    r = client.post("/protegido", headers=_bearer(token))
    assert r.status_code == 401 and b"token_revoked" in r.data
    assert app.calls == ["protegido"]  # la segunda vez la vista no se ejecutó


def test_revocar_un_token_no_afecta_a_otro(client, layer):
    t1, c1 = _token()
    t2, _ = _token()
    layer.revoke_jti(c1["jti"], 600)
    assert client.post("/protegido", headers=_bearer(t1)).status_code == 401
    assert client.post("/protegido", headers=_bearer(t2)).status_code == 200


# ----------------------------------------------------------------- 403: roles
def test_rol_insuficiente_es_403_y_no_ejecuta_la_vista(client, app):
    token, _ = _token(role_id=ROLE_CUSTOMER)
    r = client.delete("/admin", headers=_bearer(token))
    assert r.status_code == 403 and b"forbidden" in r.data
    assert app.calls == []


def test_admin_puede_operaciones_de_admin(client):
    token, _ = _token(role_id=ROLE_ADMIN)
    assert client.delete("/admin", headers=_bearer(token)).status_code == 200


@pytest.mark.parametrize("rol,esperado", [(ROLE_ADMIN, 200), (ROLE_STAFF, 200), (ROLE_CUSTOMER, 403)])
def test_varios_roles_permitidos(client, rol, esperado):
    token, _ = _token(role_id=rol)
    assert client.patch("/gestion", headers=_bearer(token)).status_code == esperado


# --------------------------------------------------------------- Redis caído
def test_redis_caido_deniega_con_503_y_no_ejecuta_la_vista(client, app, redis_down):
    token, _ = _token(role_id=ROLE_ADMIN)
    r = client.delete("/admin", headers=_bearer(token))
    assert r.status_code == 503 and b"redis_unavailable" in r.data
    assert app.calls == []


# ----------------------------------------------------------------- logs y métricas
def test_el_token_y_el_header_nunca_se_registran(client, caplog):
    caplog.set_level(logging.DEBUG)
    bueno, _ = _token()
    malo, _ = _token(secret="otra-clave-distinta-" + "z" * 24)
    client.post("/protegido", headers=_bearer(bueno))
    client.post("/protegido", headers=_bearer(malo))
    client.post("/protegido", headers={"Authorization": "Bearer basura"})
    registro = "\n".join(r.getMessage() for r in caplog.records)
    assert bueno not in registro and malo not in registro and "basura" not in registro
    assert "Authorization" not in registro


def test_metricas_de_autenticacion(client, metrics, layer):
    token, claims = _token()
    client.post("/protegido", headers=_bearer(token))
    client.post("/protegido")
    layer.revoke_jti(claims["jti"], 60)
    client.post("/protegido", headers=_bearer(token))
    assert metrics.get("auth_ok_total") == 1
    assert metrics.get("auth_rejected_total", reason="token_missing") == 1
    assert metrics.get("auth_rejected_total", reason="token_revoked") == 1
