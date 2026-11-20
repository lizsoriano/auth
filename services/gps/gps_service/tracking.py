"""Rastreo de pedidos: un vehículo de reparto simulado por pedido, ligado a la sesión (JWT) del usuario.

El servicio GPS original solo difunde posiciones; no conoce pedidos ni usuarios. Esta adaptación mínima agrega:

  * Código de rastreo `LIB-MTY-<año>-<id del pedido en 6 dígitos>` (p. ej. LIB-MTY-2026-000125). Se deduce del pedido real,
    así que el mismo pedido siempre tiene el mismo código y se puede volver a consultar sin guardar nada.
  * Autorización: el JWT (HS256, el mismo del servicio login) se valida aquí y el dueño del pedido lo decide el servicio
    **pedidos** (GET /pedidos/<id> con el mismo Bearer): un cliente solo ve sus pedidos (lo ajeno es 404) y staff/admin ven todos.
    No se duplican las reglas de pedidos.
  * Solo se rastrean pedidos ya pagados («pagado» o «enviado»): nunca se inventa un pago.
  * Una simulación por pedido: sale de la librería (Macroplaza) y recorre calles reales de Monterrey (las rutas OSRM de
    data/rutas_monterrey.geojson) hasta un destino que depende del pedido. «Entregado» ocurre solo al llegar al final de la ruta.

La simulación es una función del tiempo (no un hilo por pedido): con el reloj se calcula en qué estado y posición va. El
tiempo del recorrido está acelerado (`TRACKING_TIME_SCALE`, 30× por omisión) para poder verlo en pocos minutos.
Límite documentado: el estado vive en memoria; si el servicio se reinicia, la simulación de un pedido vuelve a empezar.
"""
import bisect
import json
import logging
import math
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt

from .store import haversine_m

log = logging.getLogger("gps_service.tracking")

CODE_RE = re.compile(r"^LIB-MTY-(\d{4})-(\d{6})$")
ALGORITHM = "HS256"
REQUIRED_CLAIMS = ("exp", "iat", "jti", "iss", "user_id", "role_id")
TRACKABLE_ORDER_STATUSES = ("pagado", "enviado")
MIN_SPEED_KMH = 10.0          # evita tiempos infinitos en tramos de velocidad casi nula
MAX_ROUTE_POINTS = 300        # puntos de la ruta que se mandan al cliente (el mapa no necesita los 1000)
MAX_DELIVERIES = 500

STATUSES = (
    ("confirmado", "Pedido confirmado"),
    ("preparando", "Preparando pedido"),
    ("enviado", "Pedido enviado"),
    ("en_ruta", "En ruta de entrega"),
    ("entregado", "Entregado"),
)
STATUS_TEXT = dict(STATUSES)


class TrackingError(Exception):
    """Error con código HTTP y un mensaje que el cliente puede mostrar tal cual."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ----------------------------------------------------------------------- JWT
def decode_token(token, secret_key, issuer):
    """Valida firma (HS256 fijo), vigencia, emisor y claims obligatorios. Lanza TrackingError(401)."""
    if not token or not isinstance(token, str):
        raise TrackingError(401, "token_missing", "Falta el token. Inicia sesión y envía el JWT.")
    try:
        claims = pyjwt.decode(token, secret_key, algorithms=[ALGORITHM], issuer=issuer,
                              options={"require": list(REQUIRED_CLAIMS)})
    except pyjwt.ExpiredSignatureError:
        raise TrackingError(401, "token_expired", "El token expiró. Renuévalo o inicia sesión de nuevo.") from None
    except pyjwt.PyJWTError:
        raise TrackingError(401, "token_invalid", "El token no es válido.") from None
    for key in ("user_id", "role_id"):
        if not isinstance(claims.get(key), int) or isinstance(claims.get(key), bool):
            raise TrackingError(401, "token_invalid", "El token no es válido.")
    return claims


def bearer_token(header):
    """Extrae el token de 'Authorization: Bearer <token>' (None si no viene o tiene otro formato)."""
    if not header:
        return None
    parts = header.split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else None


# ------------------------------------------------------------ servicio pedidos
class OrdersClient:
    """Pregunta al servicio real de pedidos por un pedido, con el JWT del propio usuario (nunca el de otra cuenta)."""

    def __init__(self, base_url, timeout=6):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_order(self, order_id, token):
        request = urllib.request.Request(
            f"{self.base_url}/pedidos/{int(order_id)}?format=json",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)["order"]
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise TrackingError(401, "token_invalid", "El servicio de pedidos rechazó el token (vencido o revocado).") from None
            if exc.code in (403, 404):
                raise TrackingError(404, "order_not_found", "No existe ese pedido o no es tuyo.") from None
            log.warning("pedidos respondió HTTP %s", exc.code)
            raise TrackingError(502, "orders_unavailable", "El servicio de pedidos no pudo confirmar el pedido.") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
            raise TrackingError(502, "orders_unavailable", "No se pudo consultar el servicio de pedidos.") from None


# ----------------------------------------------------------------- rutas reales
def _bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


class Route:
    """Tramo de una ruta real: del origen hasta el vértice más cercano a un destino. Calcula posición según el tiempo simulado."""

    def __init__(self, name, coords, segments, origin_name, destination_name):
        self.name = name
        self.coords = coords                          # [(lat, lon), ...]
        self.origin_name, self.destination_name = origin_name, destination_name
        n = len(coords)
        self.speed_kmh = [MIN_SPEED_KMH] * n
        self.street = [""] * n
        for seg in segments:
            for i in range(seg["start"], min(seg["end"] + 1, n)):
                self.speed_kmh[i] = max(float(seg.get("speed_kmh") or MIN_SPEED_KMH), MIN_SPEED_KMH)
                self.street[i] = seg.get("street") or ""
        self.cum_m, self.cum_s = [0.0], [0.0]
        for i in range(n - 1):
            d = haversine_m(*coords[i], *coords[i + 1])
            self.cum_m.append(self.cum_m[-1] + d)
            self.cum_s.append(self.cum_s[-1] + d / (self.speed_kmh[i] / 3.6))
        self.total_m, self.total_s = self.cum_m[-1], self.cum_s[-1]

    def at(self, sim_seconds):
        """(índice del tramo, lat, lon, rumbo, velocidad km/h, metros recorridos) a los `sim_seconds` de viaje simulado."""
        if sim_seconds <= 0:
            heading = _bearing(*self.coords[0], *self.coords[1]) if len(self.coords) > 1 else 0.0
            return 0, *self.coords[0], heading, self.speed_kmh[0], 0.0
        if sim_seconds >= self.total_s:
            last = len(self.coords) - 1
            heading = _bearing(*self.coords[last - 1], *self.coords[last]) if last else 0.0
            return last, *self.coords[last], heading, 0.0, self.total_m
        i = bisect.bisect_right(self.cum_s, sim_seconds) - 1
        edge_s = self.cum_s[i + 1] - self.cum_s[i]
        frac = (sim_seconds - self.cum_s[i]) / edge_s if edge_s > 0 else 0.0
        (la1, lo1), (la2, lo2) = self.coords[i], self.coords[i + 1]
        meters = self.cum_m[i] + frac * (self.cum_m[i + 1] - self.cum_m[i])
        return i, la1 + (la2 - la1) * frac, lo1 + (lo2 - lo1) * frac, _bearing(la1, lo1, la2, lo2), self.speed_kmh[i], meters

    def thinned(self, upto_index=None):
        """Puntos [lat, lon] (máx. MAX_ROUTE_POINTS) de toda la ruta o hasta el índice dado, siempre con el último."""
        points = self.coords if upto_index is None else self.coords[: upto_index + 1]
        step = max(1, math.ceil(len(points) / MAX_ROUTE_POINTS))
        out = [[round(p[0], 6), round(p[1], 6)] for p in points[::step]]
        last = [round(points[-1][0], 6), round(points[-1][1], 6)]
        if out[-1] != last:
            out.append(last)
        return out


def load_routes(path):
    """Rutas OSRM reales del proyecto (data/rutas_monterrey.geojson) como lista de dicts listos para armar Route."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    routes = []
    for feature in data["features"]:
        props = feature["properties"]
        routes.append({
            "name": props["name"],
            "coords": [(lat, lon) for lon, lat in feature["geometry"]["coordinates"]],
            "segments": props.get("segments", []),
            "waypoints": props.get("waypoints", []),
        })
    return routes


def build_route_for_order(routes, order_id):
    """Elige ruta y destino según el pedido: otro pedido, otro recorrido (el mismo pedido siempre el mismo)."""
    route = routes[order_id % len(routes)]
    candidates = route["waypoints"][1:] or route["waypoints"]
    waypoint = candidates[(order_id // len(routes)) % len(candidates)]
    coords = route["coords"]
    end = min(range(1, len(coords)), key=lambda i: haversine_m(*coords[i], waypoint["latitude"], waypoint["longitude"]))
    origin_name = route["waypoints"][0]["name"] if route["waypoints"] else "Librería Library"
    return Route(route["name"], coords[: end + 1], route["segments"], origin_name, waypoint["name"])


# ------------------------------------------------------------------- entrega
class Delivery:
    """Entrega simulada de un pedido. Todo se calcula a partir de `now` (reloj monótono) y de la hora de inicio."""

    def __init__(self, code, order, route, started_at, started_wall, phases, time_scale):
        self.code = code
        self.order_id = order["order_id"]
        self.user_id = order["user_id"]
        self.route = route
        self.started_at, self.started_wall = started_at, started_wall
        self.t_prepare, self.t_ship, self.t_depart = phases[0], phases[0] + phases[1], phases[0] + phases[1] + phases[2]
        self.time_scale = time_scale
        self.trip_real_s = route.total_s / time_scale
        self.summary = {"total": str(order.get("total")), "items": order.get("items", [])}

    def status_at(self, now):
        elapsed = now - self.started_at
        if elapsed < self.t_prepare:
            return "confirmado"
        if elapsed < self.t_ship:
            return "preparando"
        if elapsed < self.t_depart:
            return "enviado"
        return "en_ruta" if (elapsed - self.t_depart) * self.time_scale < self.route.total_s else "entregado"

    def state(self, now, with_route=False):
        elapsed = max(0.0, now - self.started_at)
        status = self.status_at(now)
        sim_s = max(0.0, (elapsed - self.t_depart) * self.time_scale)
        index, lat, lon, heading, speed, meters = self.route.at(sim_s)
        if status != "en_ruta":
            speed = 0.0
        progress = 1.0 if status == "entregado" else (meters / self.route.total_m if self.route.total_m else 0.0)
        destination = self.route.coords[-1]
        state = {
            "code": self.code, "order_id": self.order_id,
            "status": status, "status_text": STATUS_TEXT[status], "delivered": status == "entregado",
            "position": {"latitude": round(lat, 6), "longitude": round(lon, 6), "speed": round(speed, 1),
                         "heading": round(heading, 1), "street": self.route.street[index]},
            "progress": round(progress, 4),
            "distance_m": round(meters, 1), "route_distance_m": round(self.route.total_m, 1),
            "eta_sim_s": round(max(0.0, self.route.total_s - sim_s)) if status != "entregado" else 0,
            "origin": {"name": self.route.origin_name, "latitude": self.route.coords[0][0], "longitude": self.route.coords[0][1]},
            "destination": {"name": self.route.destination_name, "latitude": destination[0], "longitude": destination[1]},
            "route_name": self.route.name, "time_scale": self.time_scale,
            "timeline": [{**item, "reached": STATUSES_ORDER[item["status"]] <= STATUSES_ORDER[status]}
                         for item in self.timeline()],
            "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if with_route:
            state["route"] = self.route.thinned()
            state["trail"] = self.route.thinned(index) if status in ("en_ruta", "entregado") else [list(self.route.coords[0])]
            if state["trail"][-1] != [state["position"]["latitude"], state["position"]["longitude"]]:
                state["trail"].append([state["position"]["latitude"], state["position"]["longitude"]])
        return state

    def timeline(self):
        offsets = {"confirmado": 0.0, "preparando": self.t_prepare, "enviado": self.t_ship,
                   "en_ruta": self.t_depart, "entregado": self.t_depart + self.trip_real_s}
        return [{"status": key, "text": text,
                 "at": (self.started_wall + timedelta(seconds=offsets[key])).isoformat(timespec="seconds")}
                for key, text in STATUSES]


STATUSES_ORDER = {key: i for i, (key, _text) in enumerate(STATUSES)}


# ------------------------------------------------------------------- manager
class TrackingManager:
    def __init__(self, *, routes_path, orders, secret_key, issuer="library-login", phases=(4.0, 8.0, 6.0),
                 time_scale=30.0, clock=time.monotonic, wall_clock=None):
        if not secret_key or len(secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY debe tener al menos 32 caracteres.")
        self.routes = load_routes(routes_path)
        self.orders = orders
        self._secret, self._issuer = secret_key, issuer
        self.phases, self.time_scale = tuple(phases), float(time_scale)
        self.clock = clock
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._deliveries = {}

    # ---- código
    @staticmethod
    def code_for(order):
        year = _order_year(order)
        return f"LIB-MTY-{year}-{int(order['order_id']):06d}"

    @staticmethod
    def order_id_from_code(code):
        match = CODE_RE.match(code or "")
        if not match:
            raise TrackingError(400, "invalid_code", "El código de rastreo debe tener el formato LIB-MTY-2026-000125.")
        order_id = int(match.group(2))
        if order_id < 1:
            raise TrackingError(400, "invalid_code", "El código de rastreo no es válido.")
        return order_id

    def authenticate(self, token):
        return decode_token(token, self._secret, self._issuer)

    # ---- acceso a una entrega
    def open(self, token, *, order_id=None, code=None):
        """Valida el JWT, pide el pedido al servicio pedidos (que decide si es del usuario) y devuelve (claims, Delivery)."""
        claims = self.authenticate(token)
        if code is not None:
            order_id = self.order_id_from_code(code)
        if not isinstance(order_id, int) or isinstance(order_id, bool) or order_id < 1:
            raise TrackingError(400, "validation_error", "order_id debe ser un entero positivo.")
        order = self.orders.get_order(order_id, token)
        expected = self.code_for(order)
        if code is not None and code != expected:
            raise TrackingError(404, "order_not_found", "El código de rastreo no corresponde a ningún pedido tuyo.")
        status = order.get("status")
        if status == "cancelado":
            raise TrackingError(409, "order_cancelled", "El pedido fue cancelado: no tiene entrega que rastrear.")
        if status not in TRACKABLE_ORDER_STATUSES:
            raise TrackingError(409, "order_not_paid", "El pedido aún no está pagado: el rastreo empieza cuando se registra el pago.")
        return claims, self._delivery(order, expected)

    def _delivery(self, order, code):
        with self._lock:
            delivery = self._deliveries.get(order["order_id"])
            if delivery is None:
                if len(self._deliveries) >= MAX_DELIVERIES:   # descarta la más antigua ya entregada (o la más antigua)
                    now = self.clock()
                    done = [k for k, d in self._deliveries.items() if d.status_at(now) == "entregado"]
                    victim = min(done or self._deliveries, key=lambda k: self._deliveries[k].started_at)
                    del self._deliveries[victim]
                route = build_route_for_order(self.routes, order["order_id"])
                delivery = Delivery(code, order, route, self.clock(), self.wall_clock(), self.phases, self.time_scale)
                self._deliveries[order["order_id"]] = delivery
                log.info("rastreo %s iniciado (ruta %s -> %s)", code, route.name, route.destination_name)
            return delivery


def _order_year(order):
    match = re.match(r"(\d{4})-\d{2}-\d{2}", str(order.get("created_at") or ""))
    return int(match.group(1)) if match else datetime.now(timezone.utc).year
