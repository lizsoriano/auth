"""Aplicación Flask + Flask-Sock: recibe posiciones de role=gps y las difunde a role=map (con GeoJSON)."""
import json
import logging
import os
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from flask_sock import Sock

from .geocode import GeocodeError, Geocoder, OutOfAreaError
from .store import Hub, ValidationError, VehicleStore, to_feature, validate_position
from .tracking import OrdersClient, TrackingError, TrackingManager, bearer_token

log = logging.getLogger("gps_service")
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ROUTES_FILE = BASE_DIR / "data" / "rutas_monterrey.geojson"
SIGNALS_FILE = BASE_DIR / "data" / "senales_viales.geojson"
MAX_BATCH = 100
GEOJSON = "application/geo+json"
TRACKING_AUTH_TIMEOUT_S = 10      # tiempo que tiene el cliente para mandar su JWT tras abrir el WebSocket
TRACKING_TICK_S = 1.0


def tracking_from_env(routes_path):
    """Rastreo de pedidos configurado por entorno; None (rastreo apagado) si falta JWT_SECRET_KEY."""
    secret = os.getenv("JWT_SECRET_KEY", "")
    if len(secret) < 32:
        log.warning("JWT_SECRET_KEY ausente o corta: el rastreo de pedidos queda desactivado")
        return None
    phases = tuple(float(os.getenv(name, default)) for name, default in
                   (("TRACKING_CONFIRMED_S", "4"), ("TRACKING_PREPARING_S", "8"), ("TRACKING_SHIPPED_S", "6")))
    return TrackingManager(
        routes_path=routes_path, orders=OrdersClient(os.getenv("PEDIDOS_URL", "http://127.0.0.1:5004")),
        secret_key=secret, issuer=os.getenv("JWT_ISSUER", "library-login").strip() or "library-login",
        phases=phases, time_scale=float(os.getenv("TRACKING_TIME_SCALE", "30")))


def create_app(history_size=None, geocoder=None, routes_file=None, signals_file=None, tracking=None):
    app = Flask(__name__, static_folder=None)
    app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}
    sock = Sock(app)
    store = VehicleStore(history_size or int(os.getenv("GPS_HISTORY_SIZE", "500")))
    hub = Hub()
    geocoder = geocoder or Geocoder()
    routes_path = Path(routes_file) if routes_file else ROUTES_FILE
    signals_path = Path(signals_file) if signals_file else SIGNALS_FILE
    if tracking is None:    # sin argumento: se configura por entorno (tracking=False lo apaga, útil en pruebas)
        tracking = tracking_from_env(routes_path) if routes_path.is_file() else None
    tracking = tracking or None
    app.extensions["gps_store"] = store
    app.extensions["gps_hub"] = hub
    app.extensions["gps_geocoder"] = geocoder
    app.extensions["gps_tracking"] = tracking

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(STATIC_DIR, filename, max_age=0)

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="gps", vehicles=store.count(), clients=hub.counts(),
                       tracking="enabled" if tracking else "disabled")

    @app.get("/vehicles")
    def vehicles():
        return jsonify(vehicles=store.snapshot())

    @app.get("/vehicles/<vehicle_id>/history")
    def vehicle_history(vehicle_id):
        history = store.history(vehicle_id)
        if history is None:
            return jsonify(error=f"No hay datos del vehículo {vehicle_id}"), 404
        return jsonify(vehicle_id=vehicle_id, count=len(history), history=history)

    # ------------------------------------------------------------- GeoJSON
    @app.get("/geojson/vehicles")
    def geojson_vehicles():
        return app.response_class(json.dumps(store.features()), mimetype=GEOJSON)

    @app.get("/geojson/routes")
    def geojson_routes():
        if not routes_path.is_file():
            return jsonify(error="Este servicio no tiene rutas GeoJSON cargadas"), 404
        return send_file(routes_path, mimetype=GEOJSON, max_age=3600)

    @app.get("/geojson/signals")
    def geojson_signals():
        """Semáforos, cruces peatonales, altos, topes, zonas escolares (OpenStreetMap) y baches (simulados) sobre las rutas."""
        if not signals_path.is_file():
            return jsonify(error="Este servicio no tiene señales viales GeoJSON cargadas"), 404
        return send_file(signals_path, mimetype=GEOJSON, max_age=3600)

    @app.get("/vehicles/<vehicle_id>/track.geojson")
    def vehicle_track(vehicle_id):
        feature = store.track_feature(vehicle_id)
        if feature is None:
            return jsonify(error=f"No hay datos del vehículo {vehicle_id}"), 404
        return app.response_class(json.dumps(feature), mimetype=GEOJSON)

    # ------------------------------------------- calle de un punto (OpenStreetMap)
    @app.get("/geocode/reverse")
    def geocode_reverse():
        try:
            lat, lon = float(request.args["lat"]), float(request.args["lon"])
        except (KeyError, ValueError):
            return jsonify(error="Indica lat y lon numéricos, por ejemplo ?lat=25.6866&lon=-100.3161"), 400
        try:
            return jsonify(geocoder.reverse(lat, lon))
        except OutOfAreaError as exc:
            return jsonify(error=str(exc)), 422
        except GeocodeError as exc:
            return jsonify(error=str(exc)), 502

    # --------------------------------------------- rastreo de pedidos (JWT + código)
    @app.errorhandler(TrackingError)
    def tracking_error(exc):
        response = jsonify(error={"code": exc.code, "message": exc.message})
        response.status_code = exc.status
        response.headers["Cache-Control"] = "no-store"
        if exc.status == 401:
            response.headers["WWW-Authenticate"] = 'Bearer realm="library"'
        return response

    def tracking_manager():
        if tracking is None:
            raise TrackingError(503, "tracking_disabled", "El rastreo de pedidos no está configurado en este servidor.")
        return tracking

    @app.post("/tracking")
    def tracking_create():
        """Inicia (o recupera) el rastreo de un pedido pagado: body {"order_id": 125} + Authorization: Bearer <JWT>."""
        manager = tracking_manager()
        data = request.get_json(silent=True)
        order_id = data.get("order_id") if isinstance(data, dict) else None
        _claims, delivery = manager.open(bearer_token(request.headers.get("Authorization")), order_id=order_id)
        return _no_store(jsonify(tracking=delivery.state(manager.clock(), with_route=True)))

    @app.get("/tracking/<code>")
    def tracking_get(code):
        """Estado actual del pedido de ese código (?route=1 agrega la ruta y lo recorrido). Solo su dueño o staff/admin."""
        manager = tracking_manager()
        _claims, delivery = manager.open(bearer_token(request.headers.get("Authorization")), code=code)
        return _no_store(jsonify(tracking=delivery.state(manager.clock(), with_route=request.args.get("route") == "1")))

    @sock.route("/ws/tracking")
    def tracking_websocket(ws):
        """Primer mensaje obligatorio: {"type":"auth","token":"<JWT>","code":"LIB-MTY-2026-000125"} (el token no va en la URL)."""
        try:
            manager = tracking_manager()
            first = _receive_json(ws, TRACKING_AUTH_TIMEOUT_S)
            if not isinstance(first, dict) or first.get("type") != "auth":
                raise TrackingError(401, "token_missing",
                                    'El primer mensaje debe ser {"type":"auth","token":"<JWT>","code":"<código de rastreo>"}')
            claims, delivery = manager.open(first.get("token"), code=first.get("code"))
        except TrackingError as exc:
            ws.send(json.dumps({"type": "error", "code": exc.code, "status": exc.status, "message": exc.message}))
            ws.close(reason=1008, message=exc.code)
            return
        log.info("rastreo %s: cliente conectado (usuario %s)", delivery.code, claims["user_id"])
        try:
            _serve_tracking(ws, manager, delivery, claims)
        finally:
            log.info("rastreo %s: cliente desconectado", delivery.code)

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


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _receive_json(ws, timeout):
    """Siguiente mensaje JSON del cliente; None si no llegó nada a tiempo o no es JSON."""
    raw = ws.receive(timeout=timeout)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _serve_tracking(ws, manager, delivery, claims):
    """Manda la foto inicial (con ruta) y una actualización por segundo hasta que llega; atiende ping y refresh de token."""
    ws.send(json.dumps({"type": "snapshot", **delivery.state(manager.clock(), with_route=True)}))
    expires_at, last_key, finished = claims["exp"], None, False
    while True:
        payload = _receive_json(ws, TRACKING_TICK_S)
        if isinstance(payload, dict):
            kind = payload.get("type")
            if kind == "ping":
                ws.send(json.dumps({"type": "pong"}))
            elif kind == "refresh":   # el cliente renovó su JWT (20 min): se valida y se extiende la sesión del rastreo
                try:
                    renewed = manager.authenticate(payload.get("token"))
                    if renewed["user_id"] != claims["user_id"]:
                        raise TrackingError(403, "forbidden", "El token nuevo es de otro usuario.")
                except TrackingError as exc:
                    ws.send(json.dumps({"type": "error", "code": exc.code, "status": exc.status, "message": exc.message}))
                else:
                    expires_at = renewed["exp"]
                    ws.send(json.dumps({"type": "token_refreshed"}))
        if time.time() >= expires_at:
            ws.send(json.dumps({"type": "error", "code": "token_expired", "status": 401,
                                "message": "El token expiró: renuévalo (mensaje refresh) o vuelve a conectar."}))
            ws.close(reason=1008, message="token_expired")
            return
        if finished:
            continue
        state = delivery.state(manager.clock())
        position = state["position"]
        key = (state["status"], position["latitude"], position["longitude"])
        if key != last_key:
            if last_key is not None and last_key[0] == state["status"]:
                state.pop("timeline")      # la línea de tiempo solo se reenvía cuando cambia el estado
            ws.send(json.dumps({"type": "update", **state}))
            last_key = key
        finished = state["delivered"]


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
        if len(positions) == 1:
            hub.broadcast_map({"type": "update", "vehicle": positions[0], "feature": to_feature(positions[0])})
        else:   # un solo mensaje por lote (escala mejor que uno por vehículo): lista + FeatureCollection GeoJSON
            hub.broadcast_map({"type": "updates", "vehicles": positions,
                               "features": {"type": "FeatureCollection", "features": [to_feature(p) for p in positions]}})
