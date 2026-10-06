import json
from types import SimpleNamespace

import pytest
from flask import g

from library_common import ApiError, ConfigError, JwtAuth, SecuritySettings
from library_common.pg import GENERIC_ERRORS, Pg
from library_common.service_kit import (
    create_base_app, is_admin, is_privileged, json_body, page_args, register_health, role_payload)
from library_common.settings import ServiceSettings

from conftest import SECRET
from test_jwt_auth import _bearer, _token


def _settings(**sec):
    return ServiceSettings(database_url="postgresql://x", security=SecuritySettings(jwt_secret_key=SECRET, **sec))


@pytest.fixture
def kit(layer, metrics):
    app, auth = create_base_app(name="demo", import_name="demo", settings=_settings(), redis_layer=layer, metrics=metrics)
    state = {"db_ok": True}

    def check():
        if not state["db_ok"]:
            raise ApiError("database_unavailable", "x", 503)

    register_health(app, "demo", check)

    @app.post("/echo")
    @auth.required(roles=("admin", "staff"))
    def echo():
        return {"user_id": g.jwt_claims["user_id"], "body": json_body(), "priv": is_privileged(), "admin": is_admin()}

    @app.get("/page")
    def page():
        return {"p": list(page_args())}

    @app.get("/boom")
    def boom():
        raise RuntimeError("secreto interno: password=hunter2")

    @app.get("/apierr")
    def apierr():
        raise ApiError("not_found", "No existe", 404)

    app.state = state
    return app


def j(r):
    return json.loads(r.get_data(as_text=True))


def test_el_kit_exige_jwt_y_valida_formato(kit):
    c = kit.test_client()
    assert c.post("/echo").status_code == 401
    assert c.get("/page?format=yaml").status_code == 400
    r = c.post("/echo?format=json", json={"a": 1}, headers=_bearer(_token(role_id=1)[0]))
    assert r.status_code == 200 and j(r)["body"] == {"a": 1} and j(r)["admin"] is True and j(r)["priv"] is True


def test_customer_no_es_privilegiado_y_recibe_403(kit):
    assert kit.test_client().post("/echo", json={}, headers=_bearer(_token(role_id=3)[0])).status_code == 403


def test_json_body_rechaza_lo_que_no_es_un_objeto(kit):
    h = _bearer(_token(role_id=2)[0])
    c = kit.test_client()
    assert c.post("/echo", data="no json", headers=h).status_code == 400
    assert c.post("/echo", json=[1, 2], headers=h).status_code == 400


@pytest.mark.parametrize("q,ok", [("", True), ("?limit=10&offset=5", True), ("?limit=0", False), ("?limit=201", False),
                                  ("?offset=-1", False), ("?limit=abc", False)])
def test_paginacion_acotada(kit, q, ok):
    assert (kit.test_client().get("/page" + q + ("&" if q else "?") + "format=json").status_code == 200) is ok


def test_errores_uniformes_sin_filtrar_detalles(kit):
    c = kit.test_client()
    r = c.get("/boom?format=json")
    assert r.status_code == 500 and "hunter2" not in r.get_data(as_text=True) and j(r)["error"]["code"] == "internal_error"
    assert c.get("/apierr?format=json").status_code == 404 and j(c.get("/apierr?format=json"))["error"]["code"] == "not_found"
    assert c.get("/no-existe?format=json").status_code == 404
    assert c.put("/page?format=json").status_code == 405
    assert b"<error>" in c.get("/apierr").data  # XML por defecto


def test_cache_control_no_store(kit):
    assert kit.test_client().get("/page").headers["Cache-Control"] == "no-store"


def test_health_con_redis_ok_y_caido(kit, redis_down):
    r = kit.test_client().get("/health?format=json")
    assert r.status_code == 200 and j(r) == {"status": "ok", "service": "demo", "database": "connected", "redis": "unavailable"}


def test_health_con_postgresql_caido_es_503(kit):
    kit.state["db_ok"] = False
    r = kit.test_client().get("/health?format=json")
    assert r.status_code == 503 and j(r)["error"]["code"] == "database_unavailable"


def test_metrics_solo_admin(kit):
    c = kit.test_client()
    assert c.get("/metrics").status_code == 401
    assert c.get("/metrics", headers=_bearer(_token(role_id=2)[0])).status_code == 403
    assert c.get("/metrics", headers=_bearer(_token(role_id=1)[0])).status_code == 200


def test_cors_solo_origenes_configurados(layer):
    app, _ = create_base_app(name="d", import_name="d", settings=_settings(cors_origins=("https://app.example",)), redis_layer=layer)
    app.add_url_rule("/x", "x", lambda: "ok")
    c = app.test_client()
    assert c.get("/x", headers={"Origin": "https://app.example"}).headers.get("Access-Control-Allow-Origin") == "https://app.example"
    assert "Access-Control-Allow-Origin" not in c.get("/x", headers={"Origin": "https://evil.example"}).headers


def test_no_arranca_sin_secreto_ni_redis(layer):
    with pytest.raises(ConfigError, match="JWT_SECRET_KEY"):
        create_base_app(name="d", import_name="d", settings=ServiceSettings(database_url="x"), redis_layer=layer)
    with pytest.raises(ConfigError, match="REDIS_URL"):
        create_base_app(name="d", import_name="d", settings=_settings())


def test_roles_constantes():
    assert role_payload() == [{"role_id": 1, "name": "admin"}, {"role_id": 2, "name": "staff"}, {"role_id": 3, "name": "customer"}]


def test_service_settings_validacion(monkeypatch):
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        ServiceSettings(security=SecuritySettings(jwt_secret_key=SECRET, redis_url="redis://x")).validate()
    with pytest.raises(ConfigError, match="BCRYPT_ROUNDS"):
        _settings(redis_url="redis://x").__class__(database_url="x", bcrypt_rounds=3,
                                                   security=SecuritySettings(jwt_secret_key=SECRET, redis_url="redis://x")).validate()
    monkeypatch.setenv("FLASK_PORT", "5009")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("REDIS_URL", "redis://:pw@127.0.0.1:6379/0")
    s = ServiceSettings.from_env(5002)
    s.validate()
    assert s.port == 5009 and s.min_password_length == 8


# ------------------------------------------------------- traducción de errores de PostgreSQL
class FakeDiag:
    message_primary = "No existe el usuario 9"


def pg_error(state):
    return SimpleNamespace(sqlstate=state, diag=FakeDiag())


def test_pg_traduce_errores_propios_genericos_y_desconocidos():
    pg = Pg("postgresql://x", errors={"US001": (404, "not_found", None), "US002": (409, "last_admin", "Último admin")})
    e = pg._translate(pg_error("US001"))
    assert (e.status, e.code, e.message) == (404, "not_found", "No existe el usuario 9")
    e = pg._translate(pg_error("US002"))
    assert (e.status, e.code, e.message) == (409, "last_admin", "Último admin")
    e = pg._translate(pg_error("23505"))
    assert (e.status, e.code) == (409, "conflict") and "constraint" not in e.message.lower()
    e = pg._translate(pg_error("XX000"))
    assert (e.status, e.code, e.message) == (500, "internal_error", "Error interno del servidor")
    assert set(GENERIC_ERRORS) >= {"23505", "23503", "23514", "23502", "22P02"}
