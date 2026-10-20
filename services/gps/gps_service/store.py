"""Validación de posiciones GPS, estado actual + historial por vehículo y difusión a los mapas."""
import json
import math
import re
import threading
from collections import deque
from datetime import datetime, timezone

VEHICLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_SPEED_KMH = 400.0
TRAIL_POINTS = 50


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


def validate_position(data, now=None):
    """Devuelve la posición normalizada (con timestamp del servidor) o lanza ValidationError."""
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
    return {
        "vehicle_id": vehicle_id,
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "speed": round(speed, 1),
        "heading": round(heading % 360, 1) % 360,
        "timestamp": stamp,
    }


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
