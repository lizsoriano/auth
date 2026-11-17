import json
import sys
import threading
import time
from pathlib import Path

import pytest
from flask import Flask, Response, jsonify, redirect, request
from flask_sock import Sock
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway_service import create_app  # noqa: E402
from gateway_service.config import SERVICES, Settings  # noqa: E402


class Served:
    """Un app de Flask en un puerto libre (los WebSockets y los timeouts no se pueden probar con test_client)."""

    def __init__(self, app):
        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.port = self.server.server_port
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def fake_service(name):
    """Servicio falso: devuelve exactamente lo que recibió para poder comprobar qué reenvía el gateway."""
    app = Flask(name)
    sock = Sock(app)
    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]

    @app.route("/echo", methods=methods)
    @app.route("/echo/<path:rest>", methods=methods)
    def echo(rest=""):
        return jsonify({"service": name, "method": request.method, "path": request.path, "rest": rest,
                        "query": request.query_string.decode(), "body": request.get_data(as_text=True),
                        "headers": {k.lower(): v for k, v in request.headers}})

    @app.route("/library/<path:rest>", methods=methods)
    def library(rest):          # el monolito sirve bajo /library: aqui llega con el prefijo
        return jsonify({"service": name, "path": request.path, "rest": rest})

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": name})

    @app.get("/slow")
    def slow():
        time.sleep(1.5)
        return "tarde"

    @app.get("/redirect")
    def to_other():
        return redirect("/echo/final", code=302)

    @app.get("/redirect-absolute")
    def to_absolute():
        return redirect(request.host_url + "echo/final", code=302)

    @app.get("/cookies")
    def cookies():
        resp = Response("ok")
        resp.set_cookie("session", "abc", httponly=True, path="/")
        resp.set_cookie("otra", "xyz", path="/")
        return resp

    @app.get("/status/<int:code>")
    def status(code):
        return Response(json.dumps({"code": code}), status=code, mimetype="application/json")

    @app.get("/xml")
    def xml():
        return Response("<ok/>", mimetype="application/xml")

    @app.get("/big")
    def big():
        return Response(b"x" * 300_000, mimetype="application/octet-stream")

    @sock.route("/ws/tracking")
    def ws_tracking(ws):
        first = ws.receive(timeout=5)
        ws.send(json.dumps({"type": "snapshot", "service": name, "echo": first,
                            "query": request.query_string.decode(),
                            "request_id": request.headers.get("X-Request-ID")}))
        while True:
            data = ws.receive(timeout=5)
            if data is None:
                return
            ws.send(f"eco:{data}")

    return app


@pytest.fixture
def stack():
    """Servicios falsos + gateway real apuntando a ellos. Devuelve (url_del_gateway, {nombre: Served})."""
    fakes = {s.name: Served(fake_service(s.name)) for s in SERVICES}
    settings = Settings(upstreams={n: f.url for n, f in fakes.items()}, connect_timeout=1.0, read_timeout=1.0,
                        max_body_bytes=2048)
    gateway = Served(create_app(settings))
    yield gateway.url, fakes
    gateway.stop()
    for f in fakes.values():
        try:
            f.stop()
        except Exception:    # noqa: BLE001 - alguno ya se detuvo dentro de la prueba
            pass
