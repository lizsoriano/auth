"""API Gateway de Library (Flask + Flask-Sock).

Es la ÚNICA puerta hacia los microservicios: Nginx publica el puerto 80 y reenvía todo aquí; los servicios (y PostgreSQL)
solo escuchan en 127.0.0.1. El gateway no reimplementa ninguna regla de negocio ni valida el JWT: enruta por prefijo,
recorta el prefijo, reenvía los encabezados (Authorization, Idempotency-Key, Cookie...) tal cual y deja que cada servicio
decida a quién atiende. Así los contratos de los servicios no cambian y un token falso sigue recibiendo 401 del servicio.

    /auth/...  /soap/...  /users/...  /authors/...  /pedidos/...  /pagos/...   ->  HTTP
    /gps/...  (incluye el WebSocket /gps/ws/tracking)                           ->  HTTP + WebSocket
"""
import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests
import websocket
from flask import Flask, Response, jsonify, request
from flask_sock import Sock
from simple_websocket import ConnectionClosed

from .config import SERVICES, Settings

log = logging.getLogger("gateway")

# Encabezados "salto a salto" (RFC 9110 §7.6.1): describen UNA conexión, no se reenvían.
HOP_BY_HOP = frozenset({"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
                        "transfer-encoding", "upgrade"})
# Los pone el gateway; se ignoran los que traiga el cliente para que nadie se haga pasar por otra IP u otro prefijo.
GATEWAY_OWNED = frozenset({"host", "content-length", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host",
                           "x-forwarded-prefix", "x-request-id"})
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def create_app(settings=None):
    settings = settings or Settings.from_env()
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = settings.max_body_bytes
    app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}
    app.json.ensure_ascii = False
    sock = Sock(app)
    services = {name: s for s in SERVICES for name in s.names}     # nombre y alias -> servicio
    session = requests.Session()     # reutiliza conexiones con los servicios (keep-alive)
    app.extensions["gateway_settings"] = settings

    # ---------------------------------------------------------------- utilidades
    def request_id():
        incoming = request.headers.get("X-Request-ID", "")
        return incoming if REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex

    def client_ip():
        return request.remote_addr or ""

    def from_trusted_proxy():
        """Solo el Nginx local (loopback) puede decir de qué IP/host/protocolo viene realmente el cliente."""
        return request.remote_addr in ("127.0.0.1", "::1")

    def forward_headers(service, rid, prefix):
        headers = {k: v for k, v in request.headers if k.lower() not in HOP_BY_HOP and k.lower() not in GATEWAY_OWNED}
        trusted = from_trusted_proxy()
        headers["X-Request-ID"] = rid
        headers["X-Forwarded-For"] = (request.headers.get("X-Forwarded-For") if trusted else None) or client_ip()
        headers["X-Forwarded-Proto"] = (request.headers.get("X-Forwarded-Proto") if trusted else None) or request.scheme
        headers["X-Forwarded-Host"] = (request.headers.get("X-Forwarded-Host") if trusted else None) or request.host
        headers["X-Forwarded-Prefix"] = prefix
        return headers

    def error(status, code, message, rid, service=None):
        body = {"error": code, "message": message, "request_id": rid}
        if service:
            body["service"] = service
        resp = jsonify(body)
        resp.status_code = status
        resp.headers["X-Request-ID"] = rid
        return resp

    def rewrite_location(value, service, upstream, prefix):
        """Un redirect del servicio apunta a SU ruta interna: se le vuelve a poner el prefijo público."""
        if value.startswith(upstream):
            value = value[len(upstream):] or "/"
        if service.keep_prefix:      # el servicio ya incluye su prefijo en sus rutas
            return value
        if value.startswith("/") and not value.startswith("//"):
            return f"{prefix}{value}"
        return value

    # ---------------------------------------------------------------- HTTP
    def proxy_http(service, rest, prefix):
        started = time.perf_counter()
        rid = request_id()
        upstream = settings.upstreams[service.name]
        url = f"{upstream}/{service.name}/{rest}" if service.keep_prefix else f"{upstream}/{rest}"
        if request.query_string:
            url += "?" + request.query_string.decode("latin-1")

        def elapsed():
            return (time.perf_counter() - started) * 1000

        try:
            resp = session.request(
                request.method, url, headers=forward_headers(service, rid, prefix), data=request.get_data(),
                allow_redirects=False, stream=True, timeout=(settings.connect_timeout, settings.read_timeout))
        except requests.exceptions.ReadTimeout:      # conectó, pero el servicio no contestó a tiempo
            log.warning("%s %s %s/%s -> 504 %.0f ms", rid, request.method, prefix, rest, elapsed())
            return error(504, "gateway_timeout", f"El servicio «{service.name}» tardó demasiado en responder.", rid,
                         service.name)
        except requests.exceptions.RequestException:   # no se pudo conectar (rechazo o tiempo de conexión)
            log.warning("%s %s %s/%s -> 502 %.0f ms", rid, request.method, prefix, rest, elapsed())
            return error(502, "bad_gateway", f"El servicio «{service.name}» no está disponible.", rid, service.name)

        # Se reenvían los bytes tal cual (sin descomprimir) y todos los encabezados salvo los de la conexión.
        out = Response(resp.raw.stream(8192, decode_content=False), status=resp.status_code)
        out.headers.clear()      # Response() trae un Content-Type por defecto; solo debe quedar el del servicio
        for key, value in resp.raw.headers.items():
            if key.lower() in HOP_BY_HOP or key.lower() in ("set-cookie", "location"):
                continue
            out.headers.add(key, value)
        for cookie in resp.raw.headers.getlist("Set-Cookie"):
            out.headers.add("Set-Cookie", cookie)
        if resp.headers.get("Location"):
            out.headers["Location"] = rewrite_location(resp.headers["Location"], service, upstream, prefix)
        out.headers["X-Request-ID"] = rid
        out.call_on_close(resp.close)
        log.info("%s %s %s/%s -> %s %.0f ms", rid, request.method, prefix, rest, resp.status_code, elapsed())
        return out

    METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

    def resolve(service_name):
        """Servicio y prefijo público para la petición actual: /api/<nombre-o-alias>/... o el prefijo antiguo /<nombre>/..."""
        service = services.get(service_name)
        via_api = request.path.startswith("/api/")
        if service is not None and via_api and service.keep_prefix:
            service = None            # el monolito no es parte de la API: vive en "/"
        return service, (f"/api/{service_name}" if via_api else f"/{service_name}")

    def route(service_name, rest):
        service, prefix = resolve(service_name)
        if service is None:
            return error(404, "unknown_service", f"No existe el servicio «{service_name}».", request_id())
        return proxy_http(service, rest, prefix)

    # Un endpoint DISTINTO por regla: con el mismo endpoint, Werkzeug "canoniza" /api/login/ redirigiendo a /login/.
    app.add_url_rule("/api/<service_name>/", endpoint="route_api_root", view_func=route, defaults={"rest": ""}, methods=METHODS)
    app.add_url_rule("/api/<service_name>/<path:rest>", endpoint="route_api", view_func=route, methods=METHODS)
    app.add_url_rule("/<service_name>/", endpoint="route_root", view_func=route, defaults={"rest": ""}, methods=METHODS)
    app.add_url_rule("/<service_name>/<path:rest>", endpoint="route_legacy", view_func=route, methods=METHODS)

    @app.errorhandler(413)
    def too_large(_exc):
        return error(413, "payload_too_large",
                     f"El cuerpo de la petición supera {settings.max_body_bytes} bytes.", request_id())

    @app.errorhandler(404)
    def not_found(_exc):
        return error(404, "not_found", "Ruta no encontrada.", request_id())

    @app.errorhandler(405)
    def not_allowed(_exc):
        return error(405, "method_not_allowed", "Método no permitido.", request_id())

    # ---------------------------------------------------------------- índice y salud
    @app.get("/")
    @app.get("/api")
    @app.get("/api/")
    def index():
        return jsonify({"service": "gateway",
                        "api": {f"/api/{n}/": s.description for s in SERVICES if not s.keep_prefix for n in s.names},
                        "routes": {f"/{s.name}/": s.description for s in SERVICES},
                        "health": "/api/health"})

    def check(service):
        try:
            r = session.get(f"{settings.upstreams[service.name]}/health", timeout=(1.5, 2.5), allow_redirects=False)
            return service.name, ("up" if r.status_code < 500 else "degraded")
        except requests.exceptions.RequestException:
            return service.name, "down"

    @app.get("/health")
    @app.get("/api/health")
    def health():
        """El gateway siempre responde si está vivo; `upstreams` dice qué servicios contestan (sin revelar sus direcciones)."""
        with ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
            states = dict(pool.map(check, SERVICES))
        overall = "ok" if all(v == "up" for v in states.values()) else "degraded"
        return jsonify({"status": overall, "service": "gateway", "upstreams": states})

    # ---------------------------------------------------------------- WebSocket (solo servicios con websocket=True)
    def websocket_proxy(client, service_name, rest):
        service, prefix = resolve(service_name)
        rid = request_id()
        if service is None or not service.websocket:
            client.close(reason=1008, message="servicio sin WebSocket")
            return
        upstream = settings.upstreams[service.name].replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        url = f"{upstream}/ws/{rest}"
        if request.query_string:
            url += "?" + request.query_string.decode("latin-1")
        try:
            up = websocket.create_connection(url, timeout=settings.connect_timeout,
                                             header=[f"X-Request-ID: {rid}", f"X-Forwarded-For: {client_ip()}",
                                                     f"X-Forwarded-Prefix: {prefix}"])
        except (OSError, websocket.WebSocketException):
            log.warning("%s WS %s/ws/%s -> no se pudo abrir el servicio", rid, prefix, rest)
            client.close(reason=1013, message="servicio no disponible")
            return
        up.settimeout(1.0)
        stop = threading.Event()
        log.info("%s WS %s/ws/%s abierto", rid, prefix, rest)

        def upstream_to_client():
            try:
                while not stop.is_set():
                    try:
                        data = up.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if data is None or data == "":
                        if not up.connected:
                            break
                        continue
                    client.send(data)
            except (websocket.WebSocketException, OSError, ConnectionClosed):
                pass
            finally:
                stop.set()

        pump = threading.Thread(target=upstream_to_client, daemon=True, name=f"ws-{rid[:8]}")
        pump.start()
        try:
            while not stop.is_set():
                try:
                    message = client.receive(timeout=1.0)
                except ConnectionClosed:
                    break
                if message is None:
                    continue
                up.send(message)
        except (websocket.WebSocketException, OSError):
            pass
        finally:
            stop.set()
            try:
                up.close()
            except Exception:    # noqa: BLE001 - cierre de cortesía
                pass
            pump.join(timeout=2)
            try:
                client.close()
            except Exception:    # noqa: BLE001
                pass
            log.info("%s WS %s/ws/%s cerrado", rid, prefix, rest)

    # sock.route() no devuelve la funcion, asi que no se pueden apilar decoradores: se registra la misma funcion dos veces.
    sock.route("/api/<service_name>/ws/<path:rest>", endpoint="websocket_api")(websocket_proxy)
    sock.route("/<service_name>/ws/<path:rest>", endpoint="websocket_legacy")(websocket_proxy)
    return app


def describe(settings):
    """Texto de arranque (sin secretos): qué prefijo va a qué servicio."""
    return json.dumps({f"/{n}/": urlsplit(u).netloc for n, u in settings.upstreams.items()}, ensure_ascii=False)
