"""Aplicación Flask + Flask-Sock: recibe posiciones de role=gps y las difunde a role=map."""
import json
import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_sock import Sock

from .store import Hub, ValidationError, VehicleStore, validate_position

log = logging.getLogger("gps_service")
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BATCH = 100


def create_app(history_size=None):
    app = Flask(__name__, static_folder=None)
    app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}
    sock = Sock(app)
    store = VehicleStore(history_size or int(os.getenv("GPS_HISTORY_SIZE", "500")))
    hub = Hub()
    app.extensions["gps_store"] = store
    app.extensions["gps_hub"] = hub

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="gps", vehicles=store.count(), clients=hub.counts())

    @app.get("/vehicles")
    def vehicles():
        return jsonify(vehicles=store.snapshot())

    @app.get("/vehicles/<vehicle_id>/history")
    def vehicle_history(vehicle_id):
        history = store.history(vehicle_id)
        if history is None:
            return jsonify(error=f"No hay datos del vehículo {vehicle_id}"), 404
        return jsonify(vehicle_id=vehicle_id, count=len(history), history=history)

    @sock.route("/ws")
    def websocket(ws):
        role = request.args.get("role")
        if role not in Hub.ROLES:
            ws.send(json.dumps({"type": "error", "message": "Indica role=gps o role=map en la URL"}))
            ws.close(reason=1008, message="role inválido")
            return
        log.info("cliente %s conectado desde %s", role, request.remote_addr)
        try:
            if role == "map":
                _serve_map(ws, store, hub)
            else:
                _serve_gps(ws, store, hub)
        finally:
            hub.remove(role, ws)
            log.info("cliente %s desconectado", role)

    return app


def _serve_map(ws, store, hub):
    ws.send(json.dumps({"type": "snapshot", "vehicles": store.snapshot()}))
    hub.add("map", ws)
    while True:
        message = ws.receive()
        if isinstance(message, str) and '"ping"' in message:
            ws.send(json.dumps({"type": "pong"}))


def _serve_gps(ws, store, hub):
    hub.add("gps", ws)
    while True:
        raw = ws.receive()
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            ws.send(json.dumps({"type": "error", "message": "El mensaje no es JSON válido"}))
            continue
        items = payload if isinstance(payload, list) else [payload]
        if not items or len(items) > MAX_BATCH:
            ws.send(json.dumps({"type": "error", "message": f"Envía de 1 a {MAX_BATCH} posiciones por mensaje"}))
            continue
        try:
            positions = [validate_position(item) for item in items]
        except ValidationError as exc:
            ws.send(json.dumps({"type": "error", "message": str(exc)}))
            continue
        for position in positions:
            store.update(position)
            hub.broadcast_map({"type": "update", "vehicle": position})
