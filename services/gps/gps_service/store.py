"""Validación de posiciones GPS, estado actual + historial por vehículo, GeoJSON y difusión a los mapas."""
import json
import math
import re
import threading
from collections import deque
from datetime import datetime, timezone

VEHICLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_SPEED_KMH = 400.0
MAX_TRIP_VALUE = 1e9          # metros o segundos de un viaje: tope generoso para rechazar basura
STREET_MAX_LEN = 120
EVENT_TEXT_MAX_LEN = 120
# Qué le está pasando al vehículo: una señal vial (la que lo hace frenar o esperar), el horario o circulación libre.
EVENT_KINDS = ("traffic_signals", "crossing", "stop", "bump", "pothole", "school", "rush", "night", "clear")
SIM_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$")
TRAIL_POINTS = 50
EARTH_RADIUS_M = 6_371_000


class ValidationError(ValueError):
    """El mensaje del simulador no cumple el contrato JSON."""


def _number(data, key, low, high, default=None):
    value = data.get(key, default)
    if value is None:
        raise ValidationError(f"Falta el campo '{key}'")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"El campo '{key}' debe ser numérico")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValidationError(f"El campo '{key}' debe estar entre {low:g} y {high:g}")
    return value


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def validate_position(data, now=None):
    """Devuelve la posición normalizada (con timestamp del servidor) o lanza ValidationError.

    Campos opcionales del simulador de rutas reales: `street` (calle actual), `avg_speed` (km/h),
    `trip_distance_m` y `trip_time_s` (lo recorrido y el tiempo empleado desde que arrancó el viaje), `event` (qué lo hace
    frenar o esperar: semáforo, cruce, alto, tope, bache, zona escolar, hora pico, noche o circulación libre),
    `event_text` (el mismo evento en texto) y `sim_time` (hora simulada HH:MM o HH:MM:SS) y `sim_day` (día simulado: 0 = lunes … 6 = domingo).
    """
    if not isinstance(data, dict):
        raise ValidationError("El mensaje debe ser un objeto JSON")
    vehicle_id = data.get("vehicle_id")
    if not isinstance(vehicle_id, str) or not VEHICLE_ID_RE.match(vehicle_id):
        raise ValidationError("vehicle_id es obligatorio (1 a 32 caracteres: letras, números, '_' o '-')")
    latitude = _number(data, "latitude", -90, 90)
    longitude = _number(data, "longitude", -180, 180)
    speed = _number(data, "speed", 0, MAX_SPEED_KMH, 0)
    heading = _number(data, "heading", 0, 360, 0)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    position = {
        "vehicle_id": vehicle_id,
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "speed": round(speed, 1),
        "heading": round(heading % 360, 1) % 360,
        "timestamp": stamp,
    }
    if data.get("street") is not None:
        street = data["street"]
        if not isinstance(street, str):
            raise ValidationError("El campo 'street' debe ser texto")
        street = "".join(ch for ch in street if ch.isprintable()).strip()
        if len(street) > STREET_MAX_LEN:
            raise ValidationError(f"El campo 'street' admite máximo {STREET_MAX_LEN} caracteres")
        if street:
            position["street"] = street
    for key, high in (("avg_speed", MAX_SPEED_KMH), ("trip_distance_m", MAX_TRIP_VALUE), ("trip_time_s", MAX_TRIP_VALUE)):
        if data.get(key) is not None:
            position[key] = round(_number(data, key, 0, high), 1)
    if data.get("event") is not None:
        if data["event"] not in EVENT_KINDS:
            raise ValidationError("El campo 'event' debe ser uno de: " + ", ".join(EVENT_KINDS))
        position["event"] = data["event"]
    if data.get("event_text") is not None:
        text = data["event_text"]
        if not isinstance(text, str):
            raise ValidationError("El campo 'event_text' debe ser texto")
        text = "".join(ch for ch in text if ch.isprintable()).strip()
        if len(text) > EVENT_TEXT_MAX_LEN:
            raise ValidationError(f"El campo 'event_text' admite máximo {EVENT_TEXT_MAX_LEN} caracteres")
        if text:
            position["event_text"] = text
    if data.get("sim_time") is not None:
        if not isinstance(data["sim_time"], str) or not SIM_TIME_RE.match(data["sim_time"]):
            raise ValidationError("El campo 'sim_time' debe ser una hora HH:MM o HH:MM:SS")
        position["sim_time"] = data["sim_time"]
    if data.get("sim_day") is not None:
        position["sim_day"] = int(_number(data, "sim_day", 0, 6))
    return position


def to_feature(position):
    """Posición como Feature GeoJSON (Point). Ojo: GeoJSON usa el orden [longitud, latitud]."""
    properties = {k: v for k, v in position.items() if k not in ("latitude", "longitude")}
    return {"type": "Feature", "id": position["vehicle_id"],
            "geometry": {"type": "Point", "coordinates": [position["longitude"], position["latitude"]]},
            "properties": properties}


def _seconds_between(first_stamp, last_stamp):
    return (datetime.fromisoformat(last_stamp) - datetime.fromisoformat(first_stamp)).total_seconds()


def average_speed_kmh(distance_m, seconds):
    """Velocidad promedio = distancia total / tiempo total (v̄ = Σd / Σt), de m/s a km/h con ×3.6.
    No es el promedio de las velocidades instantáneas."""
    return distance_m / seconds * 3.6 if seconds > 0 and distance_m >= 0 else 0.0


class VehicleStore:
    """Estado actual e historial acotado de cada vehículo, en memoria."""

    def __init__(self, history_size=500):
        self._lock = threading.Lock()
        self._history_size = history_size
        self._vehicles = {}

    def update(self, position):
        with self._lock:
            entry = self._vehicles.setdefault(
                position["vehicle_id"], {"current": None, "history": deque(maxlen=self._history_size)})
            entry["current"] = position
            entry["history"].append(position)
        return position

    def snapshot(self, trail=TRAIL_POINTS):
        with self._lock:
            return [
                {**entry["current"],
                 "trail": [[p["latitude"], p["longitude"]] for p in list(entry["history"])[-trail:]]}
                for _, entry in sorted(self._vehicles.items())
            ]

    def history(self, vehicle_id):
        with self._lock:
            entry = self._vehicles.get(vehicle_id)
            return None if entry is None else list(entry["history"])

    def count(self):
        with self._lock:
            return len(self._vehicles)

    # --------------------------------------------------------------- GeoJSON
    def features(self):
        """FeatureCollection con la posición actual de cada vehículo (Points)."""
        with self._lock:
            currents = [entry["current"] for _, entry in sorted(self._vehicles.items())]
        return {"type": "FeatureCollection", "features": [to_feature(p) for p in currents]}

    def track_feature(self, vehicle_id):
        """Recorrido del historial como Feature LineString, con distancia y velocidad promedio del tramo registrado."""
        history = self.history(vehicle_id)
        if history is None:
            return None
        coords = [[p["longitude"], p["latitude"]] for p in history]
        distance = sum(haversine_m(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:]))
        avg, method = None, "sin datos suficientes (hacen falta 2 posiciones)"
        if len(history) >= 2:
            first, last = history[0], history[-1]
            if all(k in first and k in last for k in ("trip_distance_m", "trip_time_s")) and last["trip_time_s"] > first["trip_time_s"]:
                avg = average_speed_kmh(last["trip_distance_m"] - first["trip_distance_m"], last["trip_time_s"] - first["trip_time_s"])
                method = "Δdistancia / Δtiempo del viaje simulado (v̄ = Σd / Σt)"
            else:
                avg = average_speed_kmh(distance, _seconds_between(first["timestamp"], last["timestamp"]))
                method = "distancia haversine / tiempo entre las marcas del servidor (v̄ = Σd / Σt)"
        properties = {"vehicle_id": vehicle_id, "points": len(history), "distance_m": round(distance, 1),
                      "avg_speed_kmh": None if avg is None else round(avg, 1), "method": method,
                      "from": history[0]["timestamp"], "to": history[-1]["timestamp"]}
        if len(coords) < 2:
            return {"type": "Feature", "properties": properties, "geometry": {"type": "Point", "coordinates": coords[0]}}
        return {"type": "Feature", "properties": properties, "geometry": {"type": "LineString", "coordinates": coords}}


class Hub:
    """Clientes WebSocket conectados, por rol ('gps' publica, 'map' escucha)."""

    ROLES = ("gps", "map")

    def __init__(self):
        self._lock = threading.Lock()
        self._clients = {role: set() for role in self.ROLES}

    def add(self, role, ws):
        with self._lock:
            self._clients[role].add(ws)

    def remove(self, role, ws):
        with self._lock:
            self._clients[role].discard(ws)

    def counts(self):
        with self._lock:
            return {role: len(clients) for role, clients in self._clients.items()}

    def broadcast_map(self, message):
        """Envía el mensaje a todos los mapas; descarta los que ya no responden."""
        data = json.dumps(message)
        with self._lock:
            targets = list(self._clients["map"])
        for ws in targets:
            try:
                ws.send(data)
            except Exception:
                self.remove("map", ws)
