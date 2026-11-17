import json

import pytest
import requests
import websocket

from gateway_service import create_app
from gateway_service.config import SERVICES, Settings


def get(url, **kw):
    return requests.get(url, timeout=5, allow_redirects=False, **kw)


# ----------------------------------------------------------------------------- enrutamiento
@pytest.mark.parametrize("name", [s.name for s in SERVICES if not s.keep_prefix])
def test_cada_prefijo_llega_a_su_servicio_y_se_recorta(stack, name):
    gw, _ = stack
    data = get(f"{gw}/{name}/echo/uno/dos").json()
    assert data["service"] == name
    assert data["path"] == "/echo/uno/dos"          # el prefijo público NO llega al servicio


def test_library_conserva_su_prefijo_porque_el_monolito_lo_usa(stack):
    gw, _ = stack
    d = get(f"{gw}/library/uploads/seed/978-1.jpg").json()
    assert d["service"] == "library" and d["path"] == "/library/uploads/seed/978-1.jpg"      # NO se recorta


ALIAS = {"login": "auth", "books": "soap", "libros": "soap", "usuarios": "users", "autores": "authors",
         "auth": "auth", "soap": "soap", "users": "users", "authors": "authors", "pedidos": "pedidos", "pagos": "pagos",
         "gps": "gps"}


@pytest.mark.parametrize("nombre,servicio", sorted(ALIAS.items()))
def test_api_llega_al_servicio_por_su_nombre_o_su_alias(stack, nombre, servicio):
    gw, _ = stack
    d = get(f"{gw}/api/{nombre}/echo/uno?x=1").json()
    assert d["service"] == servicio and d["path"] == "/echo/uno" and d["query"] == "x=1"     # /api/<nombre> se recorta
    assert d["headers"]["x-forwarded-prefix"] == f"/api/{nombre}"


def test_api_conserva_los_prefijos_antiguos_y_no_expone_el_monolito(stack):
    gw, _ = stack
    assert get(f"{gw}/auth/echo").json()["service"] == "auth"                # compatibilidad con las apps ya entregadas
    assert get(f"{gw}/api/library/uploads/x.jpg").status_code == 404         # el monolito vive en "/", no en /api
    assert get(f"{gw}/api/nadie/echo").json()["error"] == "unknown_service"


@pytest.mark.parametrize("ruta", ["/api/pedidos/", "/api/login/", "/pedidos/", "/auth/"])
def test_la_raiz_de_un_servicio_no_se_redirige_a_otro_prefijo(stack, ruta):
    gw, _ = stack
    r = get(f"{gw}{ruta}")
    assert r.status_code == 404 and "Location" not in r.headers      # el 404 es del servicio falso, no una redireccion


def test_api_indice_y_health(stack):
    gw, _ = stack
    for path in ("/api", "/api/"):
        api = get(f"{gw}{path}").json()["api"]
        assert "/api/login/" in api and "/api/books/" in api and "/api/usuarios/" in api and "/api/library/" not in api
    h = get(f"{gw}/api/health").json()
    assert h["service"] == "gateway" and h["upstreams"]["auth"] == "up"


def test_api_reescribe_redirecciones_con_el_prefijo_usado(stack):
    gw, _ = stack
    assert get(f"{gw}/api/login/redirect").headers["Location"] == "/api/login/echo/final"
    assert get(f"{gw}/api/books/redirect-absolute").headers["Location"] == "/api/books/echo/final"


def test_query_string_y_metodos(stack):
    gw, _ = stack
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        r = requests.request(method, f"{gw}/pedidos/echo?limit=5&q=a%20b", data=b'{"x":1}', timeout=5)
        d = r.json()
        assert d["method"] == method and d["query"] == "limit=5&q=a%20b" and d["body"] == '{"x":1}'


def test_servicio_desconocido_404_json(stack):
    gw, _ = stack
    r = get(f"{gw}/nadie/echo")
    assert r.status_code == 404 and r.json()["error"] == "unknown_service"
    assert r.headers["X-Request-ID"] == r.json()["request_id"]


def test_indice_lista_las_rutas(stack):
    gw, _ = stack
    routes = get(f"{gw}/").json()["routes"]
    assert set(routes) == {f"/{s.name}/" for s in SERVICES}


# ----------------------------------------------------------------------------- encabezados
def test_authorization_idempotency_y_cookie_viajan_sin_cambios(stack):
    gw, _ = stack
    h = get(f"{gw}/pagos/echo", headers={"Authorization": "Bearer abc.def.ghi", "Idempotency-Key": "k-123",
                                         "Cookie": "session=zzz", "X-Otro": "1"}).json()["headers"]
    assert h["authorization"] == "Bearer abc.def.ghi"
    assert h["idempotency-key"] == "k-123"
    assert h["cookie"] == "session=zzz" and h["x-otro"] == "1"


def test_encabezados_forwarded_los_pone_el_gateway(stack):
    gw, _ = stack
    h = get(f"{gw}/users/echo", headers={"X-Forwarded-Prefix": "/falso"}).json()["headers"]
    assert h["x-forwarded-prefix"] == "/users"
    assert h["x-forwarded-for"] == "127.0.0.1"
    assert h["x-request-id"]


def test_request_id_valido_se_conserva_y_uno_raro_se_reemplaza(stack):
    gw, _ = stack
    r = get(f"{gw}/auth/echo", headers={"X-Request-ID": "trazar-2026-0001"})
    assert r.headers["X-Request-ID"] == "trazar-2026-0001"
    assert r.json()["headers"]["x-request-id"] == "trazar-2026-0001"
    r = get(f"{gw}/auth/echo", headers={"X-Request-ID": "malo con espacios y simbolos <>"})
    assert r.headers["X-Request-ID"] != "malo con espacios y simbolos <>" and len(r.headers["X-Request-ID"]) == 32


def test_set_cookie_multiples_se_conservan(stack):
    gw, _ = stack
    r = get(f"{gw}/auth/cookies")
    cookies = r.raw.headers.getlist("Set-Cookie")
    assert len(cookies) == 2 and any(c.startswith("session=abc") for c in cookies)


# ----------------------------------------------------------------------------- respuestas
def test_codigos_de_estado_del_servicio_se_respetan(stack):
    gw, _ = stack
    for code in (200, 201, 204, 400, 401, 403, 404, 409, 422, 503):
        assert get(f"{gw}/pedidos/status/{code}").status_code == code


def test_el_gateway_no_inventa_el_401_lo_da_el_servicio(stack):
    gw, _ = stack
    r = get(f"{gw}/pedidos/status/401")
    assert r.json() == {"code": 401}          # el cuerpo es el del servicio, no uno del gateway


def test_redirects_se_reescriben_con_el_prefijo(stack):
    gw, _ = stack
    assert get(f"{gw}/auth/redirect").headers["Location"] == "/auth/echo/final"
    assert get(f"{gw}/auth/redirect-absolute").headers["Location"] == "/auth/echo/final"


def test_content_type_del_servicio_llega_una_sola_vez(stack):
    gw, _ = stack
    r = get(f"{gw}/soap/xml")
    assert r.headers["Content-Type"] == "application/xml; charset=utf-8"      # sin duplicar ni mezclar con text/html
    assert len(r.raw.headers.getlist("Content-Type")) == 1
    assert get(f"{gw}/soap/echo").headers["Content-Type"].startswith("application/json")


def test_respuesta_grande_pasa_completa(stack):
    gw, _ = stack
    assert len(get(f"{gw}/soap/big").content) == 300_000


def test_head(stack):
    gw, _ = stack
    assert requests.head(f"{gw}/soap/echo", timeout=5).status_code == 200


# ----------------------------------------------------------------------------- errores del gateway
def test_cuerpo_demasiado_grande_413(stack):
    gw, _ = stack
    r = requests.post(f"{gw}/pedidos/echo", data=b"x" * 5000, timeout=5)
    assert r.status_code == 413 and r.json()["error"] == "payload_too_large"


def test_servicio_caido_502(stack):
    gw, fakes = stack
    fakes["pagos"].stop()
    r = get(f"{gw}/pagos/echo")
    assert r.status_code == 502 and r.json()["error"] == "bad_gateway" and r.json()["service"] == "pagos"
    assert get(f"{gw}/users/echo").status_code == 200       # los demás siguen sirviendo


def test_servicio_lento_504(stack):
    gw, _ = stack
    r = get(f"{gw}/users/slow")
    assert r.status_code == 504 and r.json()["error"] == "gateway_timeout"


# ----------------------------------------------------------------------------- health
def test_health_agrega_el_estado_de_los_servicios(stack):
    gw, fakes = stack
    h = get(f"{gw}/health").json()
    assert h["status"] == "ok" and set(h["upstreams"]) == {s.name for s in SERVICES}
    assert all(v == "up" for v in h["upstreams"].values())
    assert "127.0.0.1:" not in json.dumps(h)                 # no revela direcciones internas
    fakes["gps"].stop()
    h = get(f"{gw}/health").json()
    assert h["status"] == "degraded" and h["upstreams"]["gps"] == "down" and h["upstreams"]["auth"] == "up"


# ----------------------------------------------------------------------------- WebSocket
def assert_closed(ws):
    """El gateway cerró el socket: websocket-client lo avisa con una excepción o devolviendo una trama vacía."""
    try:
        assert ws.recv() in ("", b"")
    except websocket.WebSocketException:
        pass


def ws_url(gw, path):
    return gw.replace("http://", "ws://") + path


def test_websocket_de_rastreo_pasa_por_el_gateway(stack):
    gw, _ = stack
    ws = websocket.create_connection(ws_url(gw, "/gps/ws/tracking?x=1"), timeout=5)
    ws.send(json.dumps({"type": "auth", "token": "t", "code": "LIB-MTY-2026-000001"}))
    snap = json.loads(ws.recv())
    assert snap["type"] == "snapshot" and snap["service"] == "gps" and snap["query"] == "x=1"
    assert json.loads(snap["echo"])["code"] == "LIB-MTY-2026-000001"     # el primer mensaje llegó intacto
    assert snap["request_id"]
    ws.send("ping")
    assert ws.recv() == "eco:ping"
    ws.close()


def test_websocket_tambien_por_api(stack):
    gw, _ = stack
    ws = websocket.create_connection(ws_url(gw, "/api/gps/ws/tracking"), timeout=5)
    ws.send("{}")
    assert json.loads(ws.recv())["service"] == "gps"
    ws.close()


def test_websocket_en_servicio_sin_websocket_se_cierra(stack):
    gw, _ = stack
    ws = websocket.create_connection(ws_url(gw, "/pedidos/ws/tracking"), timeout=5)
    assert_closed(ws)


def test_websocket_con_servicio_caido_se_cierra(stack):
    gw, fakes = stack
    fakes["gps"].stop()
    ws = websocket.create_connection(ws_url(gw, "/gps/ws/tracking"), timeout=5)
    assert_closed(ws)


def test_cierre_del_cliente_no_rompe_el_gateway(stack):
    gw, _ = stack
    ws = websocket.create_connection(ws_url(gw, "/gps/ws/tracking"), timeout=5)
    ws.send("{}")
    ws.recv()
    ws.close()
    assert get(f"{gw}/gps/echo").status_code == 200


# ----------------------------------------------------------------------------- configuración
def test_config_por_entorno():
    s = Settings.from_env({"PEDIDOS_URL": "http://10.0.0.5:9999/", "GATEWAY_READ_TIMEOUT": "7"})
    assert s.upstreams["pedidos"] == "http://10.0.0.5:9999" and s.read_timeout == 7
    assert s.upstreams["auth"] == "http://127.0.0.1:5000" and s.upstreams["gps"] == "http://127.0.0.1:5900"


def test_create_app_sin_argumentos_usa_el_entorno():
    app = create_app()
    assert app.extensions["gateway_settings"].upstreams["soap"] == "http://127.0.0.1:5001"


def test_env_example_es_valido_para_systemd_y_para_el_gateway():
    """systemd no admite comentarios en la misma linea que el valor: '3  # texto' llegaria como el valor completo."""
    from pathlib import Path
    env = {}
    for raw in (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "#" not in line, f"comentario en la misma linea: {raw!r}"
        key, _, value = line.partition("=")
        env[key] = value
    settings = Settings.from_env(env)        # no debe lanzar ValueError
    assert settings.connect_timeout == 3 and settings.read_timeout == 30 and settings.max_body_bytes == 1_048_576
