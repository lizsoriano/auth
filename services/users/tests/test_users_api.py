"""Users contra PostgreSQL REAL (migraciones 006-011) y Redis simulado. Se omiten sin TEST_DATABASE_URL."""
import json

import pytest
from library_common import passwords
from library_common.testing import admin_conn, bearer, token_for, unique

NEW = {"nombre": "Luis", "apellido_paterno": "Pérez", "apellido_materno": "Gómez", "password": "ClaveSegura123"}


def js(r):
    return json.loads(r.get_data(as_text=True))


def new_payload(**extra):
    return {**NEW, "email": f"{unique('n')}@Example.com", **extra}


@pytest.fixture
def admin(make_user):
    return make_user(role_id=1)


def post_user(client, admin, **extra):
    return client.post("/users?format=json", json=new_payload(**extra), headers=bearer(1, admin["user_id"]))


# ------------------------------------------------------------------ 401 / 403
@pytest.mark.parametrize("method,path", [("get", "/users"), ("get", "/users/1"), ("get", "/users/me"),
                                         ("post", "/users"), ("put", "/users/1"), ("patch", "/users/1"),
                                         ("delete", "/users/1"), ("put", "/users/1/password"), ("get", "/roles")])
def test_sin_token_es_401(client, method, path):
    r = getattr(client, method)(path + "?format=json", json={})
    assert r.status_code == 401 and js(r)["error"]["code"] == "token_missing"


def test_token_revocado_expirado_y_mal_firmado_son_401(client, layer, admin):
    token, claims = token_for(1, admin["user_id"])
    layer.revoke_jti(claims["jti"], 600)
    assert client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/users/me", headers=bearer(1, admin["user_id"], secret="otra-clave-" + "z" * 30)).status_code == 401


def test_customer_y_staff_no_administran_usuarios_403(client, make_user):
    for role in (2, 3):
        u = make_user(role_id=role)
        h = bearer(role, u["user_id"])
        assert client.get("/users?format=json", headers=h).status_code == 403
        assert client.post("/users?format=json", json=new_payload(), headers=h).status_code == 403
        assert client.put("/users/1?format=json", json={}, headers=h).status_code == 403
        assert client.delete("/users/1?format=json", headers=h).status_code == 403


# -------------------------------------------------------------------- admin
def test_admin_crea_lista_obtiene_y_borra(client, admin):
    h = bearer(1, admin["user_id"])
    r = post_user(client, admin, role_id=2)
    body = js(r)
    assert r.status_code == 201 and body["user"]["role_id"] == 2 and body["user"]["role_name"] == "staff"
    assert "password" not in json.dumps(body) and "password_hash" not in json.dumps(body)
    uid = body["user"]["user_id"]
    assert body["user"]["email"].endswith("@example.com") and body["user"]["email"] == body["user"]["email"].lower()
    assert body["user"]["display_name"] == "Luis Pérez Gómez" and body["user"]["email_verified_at"] is not None

    listed = js(client.get("/users?format=json&limit=500", headers=h))
    assert listed["error"]["code"] == "validation_error"
    listed = js(client.get("/users?format=json&limit=200", headers=h))
    assert uid in [u["user_id"] for u in listed["users"]]
    assert client.get(f"/users/{uid}?format=json", headers=h).status_code == 200

    assert client.delete(f"/users/{uid}?format=json", headers=h).status_code == 200
    assert client.get(f"/users/{uid}?format=json", headers=h).status_code == 404
    assert client.delete(f"/users/{uid}?format=json", headers=h).status_code == 404


def test_rol_por_defecto_customer_y_xml_por_defecto(client, admin):
    r = client.post("/users", json=new_payload(), headers=bearer(1, admin["user_id"]))
    assert r.status_code == 201 and b"<role_name>customer</role_name>" in r.data and r.mimetype == "application/xml"


def test_correo_repetido_aunque_cambie_la_mayuscula_es_409(client, admin):
    email = f"{unique('d')}@example.com"
    assert post_user(client, admin, email=email).status_code == 201
    r = post_user(client, admin, email=email.upper())
    assert r.status_code == 409 and js(r)["error"]["code"] == "conflict" and "constraint" not in js(r)["error"]["message"].lower()


@pytest.mark.parametrize("extra,campo", [
    ({"email": "no-es-correo"}, "email"), ({"password": "corta"}, "password"), ({"password": "x" * 80}, "password"),
    ({"nombre": ""}, "nombre"), ({"apellido_paterno": None}, "apellido_paterno"), ({"role_id": 9}, "role_id"),
    ({"role_id": "1"}, "role_id")])
def test_validacion_de_alta_400(client, admin, extra, campo):
    r = post_user(client, admin, **extra)
    assert r.status_code == 400 and campo in json.dumps(js(r)["error"]["details"])


def test_el_alta_no_acepta_cuerpo_que_no_es_json(client, admin):
    assert client.post("/users?format=json", data="x", headers=bearer(1, admin["user_id"])).status_code == 400


def test_put_exige_todos_los_campos_y_patch_acepta_parciales(client, admin, make_user):
    target = make_user()
    h = bearer(1, admin["user_id"])
    assert client.put(f"/users/{target['user_id']}?format=json", json={"email": "a@b.co"}, headers=h).status_code == 400
    full = {"email": f"{unique('p')}@example.com", "display_name": "Nuevo Nombre", "nombre": "N", "apellido_paterno": "P",
            "apellido_materno": "M", "role_id": 2, "is_active": True}
    r = client.put(f"/users/{target['user_id']}?format=json", json=full, headers=h)
    assert r.status_code == 200 and js(r)["user"]["role_name"] == "staff" and js(r)["user"]["nombre"] == "N"
    r = client.patch(f"/users/{target['user_id']}?format=json", json={"is_active": False}, headers=h)
    assert r.status_code == 200 and js(r)["user"]["is_active"] is False and js(r)["user"]["role_id"] == 2


@pytest.mark.parametrize("body", [{}, {"password_hash": "x"}, {"role_id": 99}, {"is_active": "si"}, {"email": ""}])
def test_patch_invalido_400(client, admin, make_user, body):
    target = make_user()
    assert client.patch(f"/users/{target['user_id']}?format=json", json=body, headers=bearer(1, admin["user_id"])).status_code == 400


def test_el_admin_no_puede_borrarse_a_si_mismo(client, admin):
    r = client.delete(f"/users/{admin['user_id']}?format=json", headers=bearer(1, admin["user_id"]))
    assert r.status_code == 409 and js(r)["error"]["code"] == "cannot_delete_self"


def test_no_se_puede_dejar_al_sistema_sin_administradores(client, admin):
    """Con un solo admin activo, ni bajarle el rol, ni desactivarlo ni borrarlo (SQLSTATE US002 -> 409)."""
    h = bearer(1, admin["user_id"])
    with admin_conn() as conn:
        others = [r[0] for r in conn.execute(
            "SELECT user_id FROM users WHERE role_id = 1 AND is_active AND user_id <> %s", (admin["user_id"],)).fetchall()]
        conn.execute("UPDATE users SET is_active = false WHERE user_id = ANY(%s)", (others,))
    try:
        other_admin = bearer(1, others[0] if others else 1)  # otro token admin para no borrarse a sí mismo
        for call in (lambda: client.patch(f"/users/{admin['user_id']}?format=json", json={"role_id": 3}, headers=h),
                     lambda: client.patch(f"/users/{admin['user_id']}?format=json", json={"is_active": False}, headers=h),
                     lambda: client.delete(f"/users/{admin['user_id']}?format=json", headers=other_admin)):
            r = call()
            assert r.status_code == 409 and js(r)["error"]["code"] == "last_admin", r.get_data(as_text=True)
    finally:
        with admin_conn() as conn:
            conn.execute("UPDATE users SET is_active = true WHERE user_id = ANY(%s)", (others,))


# -------------------------------------------------------------- autoservicio
def test_el_cliente_consulta_y_edita_solo_su_cuenta(client, make_user):
    me, other = make_user(), make_user()
    h = bearer(3, me["user_id"])
    r = client.get("/users/me?format=json", headers=h)
    assert r.status_code == 200 and js(r)["user"]["user_id"] == me["user_id"]
    assert client.get(f"/users/{me['user_id']}?format=json", headers=h).status_code == 200
    assert client.get(f"/users/{other['user_id']}?format=json", headers=h).status_code == 403
    assert client.patch(f"/users/{other['user_id']}?format=json", json={"nombre": "X"}, headers=h).status_code == 403

    r = client.patch(f"/users/{me['user_id']}?format=json",
                     json={"nombre": "Ana", "apellido_paterno": "L", "apellido_materno": "D"}, headers=h)
    assert r.status_code == 200 and js(r)["user"]["nombre"] == "Ana"


def test_el_cliente_no_puede_cambiarse_el_rol_ni_el_estado_403(client, make_user):
    me = make_user()
    h = bearer(3, me["user_id"])
    for body in ({"role_id": 1}, {"is_active": False}):
        assert client.patch(f"/users/{me['user_id']}?format=json", json=body, headers=h).status_code == 403
    with admin_conn() as conn:
        assert conn.execute("SELECT role_id FROM users WHERE user_id = %s", (me["user_id"],)).fetchone()[0] == 3


def test_staff_tambien_es_solo_autoservicio(client, make_user):
    staff, other = make_user(role_id=2), make_user()
    assert client.get(f"/users/{other['user_id']}?format=json", headers=bearer(2, staff["user_id"])).status_code == 403
    assert client.get("/users/me?format=json", headers=bearer(2, staff["user_id"])).status_code == 200


def test_usuario_borrado_con_token_vigente_recibe_404(client, make_user):
    ghost = make_user()
    h = bearer(3, ghost["user_id"])
    with admin_conn() as conn:
        conn.execute("DELETE FROM users WHERE user_id = %s", (ghost["user_id"],))
    assert client.get("/users/me?format=json", headers=h).status_code == 404


# ---------------------------------------------------------------- contraseña
def hash_of(user_id):
    with admin_conn() as conn:
        return conn.execute("SELECT password_hash FROM users WHERE user_id = %s", (user_id,)).fetchone()[0]


def test_el_dueno_cambia_su_contrasena_con_la_actual(client, make_user):
    me = make_user()
    h = bearer(3, me["user_id"])
    url = f"/users/{me['user_id']}/password?format=json"
    assert client.put(url, json={"password": "OtraClave12345"}, headers=h).status_code == 401
    assert client.put(url, json={"password": "OtraClave12345", "current_password": "incorrecta"}, headers=h).status_code == 401
    assert client.put(url, json={"password": "corta", "current_password": me["password"]}, headers=h).status_code == 400
    assert passwords.verify_password(hash_of(me["user_id"]), me["password"])  # nada cambió con los intentos fallidos
    assert client.put(url, json={"password": "OtraClave12345", "current_password": me["password"]}, headers=h).status_code == 200
    stored = hash_of(me["user_id"])
    assert stored.startswith("$2") and passwords.verify_password(stored, "OtraClave12345")
    assert not passwords.verify_password(stored, me["password"])


def test_el_admin_restablece_la_contrasena_sin_la_actual(client, admin, make_user):
    target = make_user()
    r = client.put(f"/users/{target['user_id']}/password?format=json", json={"password": "Restablecida123"},
                   headers=bearer(1, admin["user_id"]))
    assert r.status_code == 200 and passwords.verify_password(hash_of(target["user_id"]), "Restablecida123")


def test_cliente_no_cambia_la_contrasena_de_otro(client, make_user):
    me, other = make_user(), make_user()
    r = client.put(f"/users/{other['user_id']}/password?format=json",
                   json={"password": "OtraClave12345", "current_password": other["password"]}, headers=bearer(3, me["user_id"]))
    assert r.status_code == 403 and passwords.verify_password(hash_of(other["user_id"]), other["password"])


# ----------------------------------------------------------- roles / Redis / logs
def test_roles(client, make_user):
    me = make_user()
    r = client.get("/roles?format=json", headers=bearer(3, me["user_id"]))
    assert [x["name"] for x in js(r)["roles"]] == ["admin", "staff", "customer"]


def test_redis_caido_deniega_503(client, make_user, redis_down):
    me = make_user()
    r = client.get("/users/me?format=json", headers=bearer(3, me["user_id"]))
    assert r.status_code == 503 and js(r)["error"]["code"] == "redis_unavailable"


def test_health_y_metrics(client, make_user):
    assert js(client.get("/health?format=json")) == {"status": "ok", "service": "users", "database": "connected", "redis": "ok"}
    assert client.get("/metrics").status_code == 401
    me = make_user()
    assert client.get("/metrics", headers=bearer(3, me["user_id"])).status_code == 403
    assert client.get("/metrics", headers=bearer(1, me["user_id"])).status_code == 200
