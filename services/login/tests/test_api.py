import json
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import pytest


def xml(response):
    assert response.mimetype == "application/xml"
    assert response.get_data(as_text=True).startswith('<?xml version="1.0" encoding="UTF-8"?>')
    return ET.fromstring(response.get_data())


def js(response):
    assert response.mimetype == "application/json"
    return json.loads(response.get_data(as_text=True))


def login(client, good, fmt="json"):
    return client.post(f"/login?format={fmt}", json={"email": good["email"], "password": good["password"]})


@pytest.fixture
def registered(client, good):
    assert client.post("/register?format=json", json=good).status_code == 201
    return good


# ------------------------------------------------------------- formato
@pytest.mark.parametrize("path,method", [("/health", "get"), ("/session", "get"), ("/login", "post"),
                                         ("/logout", "post"), ("/register", "post"),
                                         ("/resend-verification", "post"), ("/verify/" + "a" * 43, "get")])
def test_default_is_xml_and_json_on_request(client, path, method):
    assert getattr(client, method)(path).mimetype == "application/xml"
    assert getattr(client, method)(path + "?format=xml").mimetype == "application/xml"
    assert getattr(client, method)(path + "?format=json").mimetype == "application/json"
    assert getattr(client, method)(path + "?format=JSON").mimetype == "application/json"


def test_invalid_format_is_400_in_xml(client):
    r = client.get("/health?format=yaml")
    assert r.status_code == 400 and xml(r).findtext("error/code") == "invalid_format"


def test_unknown_route_and_method_use_requested_format(client):
    assert js(client.get("/nope?format=json"))["error"]["code"] == "not_found"
    r = client.get("/login")  # GET sobre ruta POST
    assert r.status_code == 405 and xml(r).findtext("error/code") == "method_not_allowed"


# ------------------------------------------------------------- register
def test_register_ok_xml_default(client, good):
    r = client.post("/register", json=good)
    assert r.status_code == 201
    root = xml(r)
    assert root.findtext("user/email") == "ana@example.com" and root.findtext("user/nombre") == "Ana"
    assert root.find("user/password_hash") is None and root.find("user/password") is None


def test_register_ok_json_never_leaks_password(client, good):
    r = client.post("/register?format=json", json=good)
    body = js(r)
    assert r.status_code == 201 and body["user"]["id"] == 1 and body["verification_email"] == "not_required"
    assert "password" not in json.dumps(body).lower()


def test_password_is_stored_only_as_hash(client, repo, good):
    client.post("/register?format=json", json=good)
    stored = repo.users["ana@example.com"]["password_hash"]
    assert good["password"] not in stored and stored.startswith("$2b$")  # bcrypt, igual que el monolito


def test_register_normalizes_email_and_names(client, repo, good):
    good.update(email="  Ana@Example.COM ", nombre="  Ana   María ")
    assert client.post("/register?format=json", json=good).status_code == 201
    assert repo.users["ana@example.com"]["nombre"] == "Ana María"


def test_register_duplicate_email_case_insensitive(client, registered):
    r = client.post("/register?format=json", json=dict(registered, email="ANA@example.com"))
    assert r.status_code == 409 and js(r)["error"]["code"] == "email_exists"


@pytest.mark.parametrize("missing", ["nombre", "apellido_paterno", "apellido_materno", "email", "password"])
def test_register_requires_every_field(client, good, missing):
    good.pop(missing)
    r = client.post("/register?format=json", json=good)
    assert r.status_code == 400
    assert [d["field"] for d in js(r)["error"]["details"]] == [missing]


@pytest.mark.parametrize("email", ["nope", "a@b", "a b@example.com", "@example.com", "ana@", "a@@example.com"])
def test_register_rejects_invalid_email(client, good, email):
    r = client.post("/register?format=json", json=dict(good, email=email))
    assert r.status_code == 400 and js(r)["error"]["details"][0]["field"] == "email"


def test_register_rejects_short_and_over_72_bytes_password(client, good):
    assert client.post("/register?format=json", json=dict(good, password="1234567")).status_code == 400
    assert client.post("/register?format=json", json=dict(good, password="x" * 73)).status_code == 400
    assert client.post("/register?format=json", json=dict(good, password="é" * 37)).status_code == 400  # 74 bytes
    assert client.post("/register?format=json", json=dict(good, password="x" * 72)).status_code == 201


def test_register_fills_display_name_for_the_monolith(client, repo, good):
    client.post("/register?format=json", json=good)
    row = repo.users["ana@example.com"]
    assert row["display_name"] == "Ana López Díaz" and row["is_active"] is True
    long = dict(good, email="l@example.com", nombre="N" * 120, apellido_paterno="P" * 120, apellido_materno="M" * 120)
    assert client.post("/register?format=json", json=long).status_code == 201
    assert len(repo.users["l@example.com"]["display_name"]) == 150   # users.display_name es varchar(150)


def test_register_validation_error_in_xml_lists_details(client, good):
    r = client.post("/register", json=dict(good, email="nope", nombre=""))
    assert r.status_code == 400
    fields = [i.findtext("field") for i in xml(r).findall("error/details/item")]
    assert fields == ["nombre", "email"]


@pytest.mark.parametrize("body", [[1, 2], "texto", 5, None])
def test_register_non_object_json_is_400_not_500(client, body):
    r = client.post("/register?format=json", data=json.dumps(body), content_type="application/json")
    assert r.status_code == 400 and js(r)["error"]["code"] == "invalid_body"


def test_register_without_body_is_400(client):
    assert client.post("/register?format=json").status_code == 400


def test_register_accepts_form_encoded(client, good):
    assert client.post("/register?format=json", data=good).status_code == 201


def test_register_non_string_values_are_400(client, good):
    assert client.post("/register?format=json", json=dict(good, nombre=123, password=["x"])).status_code == 400


# ---------------------------------------------------------------- login
def test_login_ok_xml_and_json(client, registered):
    r = login(client, registered, "xml")
    assert r.status_code == 200
    root = xml(r)
    assert root.findtext("message") == "Sesión iniciada" and root.findtext("session/expires_in_seconds") == "1800"
    assert client.get_cookie("login_session") is not None
    assert js(login(client, registered, "json"))["user"]["email"] == "ana@example.com"


def test_login_email_is_case_insensitive_and_trimmed(client, registered):
    r = client.post("/login?format=json", json={"email": "  ANA@Example.com ", "password": registered["password"]})
    assert r.status_code == 200


def test_login_wrong_password_and_unknown_user_look_identical(client, registered):
    a = client.post("/login?format=json", json={"email": registered["email"], "password": "incorrecta"})
    b = client.post("/login?format=json", json={"email": "nadie@example.com", "password": "incorrecta"})
    assert a.status_code == b.status_code == 401
    assert js(a) == js(b) and js(a)["error"]["code"] == "invalid_credentials"
    assert client.get_cookie("login_session") is None


@pytest.mark.parametrize("payload", [{}, {"email": "a@b.co"}, {"password": "x"}, {"email": "", "password": ""}])
def test_login_missing_fields_400(client, payload):
    assert client.post("/login?format=json", json=payload).status_code == 400


def test_login_disabled_account_403(client, registered, repo):
    repo.users["ana@example.com"]["is_active"] = False
    r = login(client, registered)
    assert r.status_code == 403 and js(r)["error"]["code"] == "account_disabled"


def test_login_with_unreadable_hash_is_401_not_500(client, registered, repo):
    for bad in ("$2b$10$abcdefghijklmnopqrstuuG0000000000000000000000000000000", "", "basura", "scrypt:32768:8:1$a$b"):
        repo.users["ana@example.com"]["password_hash"] = bad
        assert login(client, registered).status_code == 401


def test_monolith_account_can_log_in(client, repo):
    """Cuenta creada por el monolito: hash bcrypt $2a$ (Node/pgcrypto), sin nombre/apellidos."""
    import bcrypt
    legacy = bcrypt.hashpw(b"CambieEstaClave123!", bcrypt.gensalt(4)).decode().replace("$2b$", "$2a$", 1)
    repo.users["admin@example.com"] = dict(user_id=7, nombre=None, apellido_paterno=None, apellido_materno=None,
                                           display_name="Administrador", email="admin@example.com",
                                           password_hash=legacy, is_active=True,
                                           created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    r = client.post("/login?format=json", json={"email": "Admin@Example.com", "password": "CambieEstaClave123!"})
    assert r.status_code == 200
    user = js(r)["user"]
    assert user["display_name"] == "Administrador" and user["nombre"] is None
    root = xml(client.get("/session"))
    assert root.findtext("user/display_name") == "Administrador" and root.find("user/nombre").text is None


def test_password_with_edge_spaces_roundtrips(client, good):
    good["password"] = "  con espacios  "
    assert client.post("/register?format=json", json=good).status_code == 201
    assert login(client, good).status_code == 200


def test_login_records_ip_and_user_agent(client, registered, repo):
    client.post("/login?format=json", json={"email": registered["email"], "password": registered["password"]},
                headers={"User-Agent": "postman-test"})
    session = next(iter(repo.sessions.values()))
    assert session["ip"] == "127.0.0.1" and session["ua"] == "postman-test"


def test_relogin_revokes_previous_session(client, registered, repo):
    login(client, registered)
    first = next(iter(repo.sessions))
    login(client, registered)
    assert repo.sessions[first]["revoked_at"] is not None and len(repo.sessions) == 2


# ---------------------------------------------------------- session/logout
def test_session_without_login_is_401(client):
    r = client.get("/session")
    assert r.status_code == 401 and xml(r).findtext("error/code") == "not_authenticated"


def test_session_active_xml_and_json(client, registered, clock):
    login(client, registered)
    clock.advance(minutes=10)
    body = js(client.get("/session?format=json"))
    assert body["authenticated"] is True and body["user"]["email"] == "ana@example.com"
    assert body["session"]["expires_in_seconds"] == 1200
    root = xml(client.get("/session"))
    assert root.findtext("authenticated") == "true" and root.findtext("user/apellido_materno") == "Díaz"


def test_session_expires_after_30_minutes(client, registered, clock):
    login(client, registered)
    clock.advance(minutes=29, seconds=59)
    assert client.get("/session?format=json").status_code == 200
    clock.advance(seconds=1)
    r = client.get("/session?format=json")
    assert r.status_code == 401
    assert js(r)["error"]["code"] == "session_expired"
    # sigue reportando "caducada" (no "no autenticado") hasta volver a iniciar sesión
    assert xml(client.get("/session")).findtext("error/code") == "session_expired"
    assert login(client, registered).status_code == 200
    assert client.get("/session?format=json").status_code == 200


def test_logout_revokes_session_server_side(client, registered, repo):
    login(client, registered)
    stolen = client.get_cookie("login_session").value
    r = client.post("/logout?format=json")
    assert r.status_code == 200 and js(r)["message"] == "Sesión cerrada"
    assert client.get("/session?format=json").status_code == 401
    client.set_cookie("login_session", stolen)  # la cookie robada ya no sirve
    assert js(client.get("/session?format=json"))["error"]["code"] == "not_authenticated"


def test_logout_without_session_401_and_twice_401(client, registered):
    assert client.post("/logout?format=json").status_code == 401
    login(client, registered)
    assert client.post("/logout").status_code == 200
    assert client.post("/logout").status_code == 401


def test_logout_after_expiry_reports_expired(client, registered, clock):
    login(client, registered)
    clock.advance(minutes=31)
    r = client.post("/logout?format=json")
    assert r.status_code == 401 and js(r)["error"]["code"] == "session_expired"


def test_tampered_cookie_is_not_authenticated(client, registered):
    login(client, registered)
    client.set_cookie("login_session", "garbage.value.here")
    assert client.get("/session?format=json").status_code == 401


def test_sessions_are_isolated_between_clients(app, registered, client):
    login(client, registered)
    other = app.test_client()
    assert other.get("/session?format=json").status_code == 401


def test_cookie_flags_and_no_store(client, registered):
    r = login(client, registered)
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and ("Max-Age" in cookie or "Expires" in cookie)
    assert r.headers["Cache-Control"] == "no-store"


# --------------------------------------------------------------- health
def test_health_ok(client):
    assert js(client.get("/health?format=json")) == {"status": "ok", "service": "login", "database": "connected", "schema": "ok"}
    assert xml(client.get("/health")).findtext("status") == "ok"


def test_health_db_down_is_503_and_hides_details(client, repo):
    repo.up = False
    r = client.get("/health?format=json")
    assert r.status_code == 503 and js(r)["error"]["code"] == "database_unavailable"
    assert "db down" not in r.get_data(as_text=True)
    assert xml(client.get("/health")).findtext("error/code") == "database_unavailable"


def test_health_missing_schema_is_503(client, repo):
    repo.schema = False
    assert js(client.get("/health?format=json"))["error"]["code"] == "schema_missing"


# -------------------------------------------------------------- swagger
def test_openapi_documents_every_endpoint_in_xml_and_json(client):
    spec = js(client.get("/openapi.json"))
    assert spec["openapi"].startswith("3.")
    expected = {"/register": "post", "/login": "post", "/logout": "post", "/session": "get", "/health": "get",
                "/verify/{token}": "get", "/resend-verification": "post"}
    for path, method in expected.items():
        op = spec["paths"][path][method]
        ok = next(r for code, r in op["responses"].items() if code.startswith("2"))
        assert set(ok["content"]) == {"application/xml", "application/json"}, path
        assert {"$ref": "#/components/parameters/format"} in op["parameters"]
    fmt = spec["components"]["parameters"]["format"]["schema"]
    assert fmt["enum"] == ["xml", "json"] and fmt["default"] == "xml"


def test_openapi_xml_examples_are_valid_xml(client):
    spec = js(client.get("/openapi.json"))
    for path in spec["paths"].values():
        for op in path.values():
            for resp in op["responses"].values():
                ET.fromstring(resp["content"]["application/xml"]["example"].split("?>", 1)[1])


def test_swagger_ui_is_served(client):
    r = client.get("/docs/")
    assert r.status_code == 200 and b"swagger" in r.data.lower()
