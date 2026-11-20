"""Reglas de tránsito de la simulación: señales viales, horarios y semáforos. Solo biblioteca estándar.

Tipos de señal (`kind`):
  traffic_signals  semáforo (ciclo verde → amarillo → rojo; de noche, amarillo intermitente)
  crossing         cruce peatonal (a veces hay peatones: el vehículo se detiene a cederles el paso)
  stop             alto
  bump             tope
  pothole          bache (simulado: OpenStreetMap no tiene baches)
  school           zona escolar (límite reducido en horario escolar)

Los semáforos, cruces, altos, topes y escuelas vienen de OpenStreetMap (ver hazards.py); los baches son simulados.
"""
import math
from dataclasses import dataclass, field

KINDS = {
    "traffic_signals": {"label": "Semáforo", "icon": "🚦", "color": "#d93025"},
    "crossing": {"label": "Cruce peatonal", "icon": "🚸", "color": "#1a73e8"},
    "stop": {"label": "Alto", "icon": "🛑", "color": "#b31412"},
    "bump": {"label": "Tope", "icon": "⚠️", "color": "#e37400"},
    "pothole": {"label": "Bache", "icon": "🕳️", "color": "#5f6368"},
    "school": {"label": "Zona escolar", "icon": "🏫", "color": "#188038"},
}
EVENT_KINDS = tuple(KINDS) + ("rush", "night", "clear")

# Horarios de Monterrey (hora local). `days` usa 0 = lunes … 6 = domingo.
DEFAULT_SCHEDULE = {
    "timezone": "America/Monterrey",
    "rush_hours": [
        {"name": "Hora pico de la mañana", "start": "07:00", "end": "09:30", "days": [0, 1, 2, 3, 4], "speed_factor": 0.60},
        {"name": "Hora pico de la comida", "start": "13:30", "end": "15:30", "days": [0, 1, 2, 3, 4], "speed_factor": 0.75},
        {"name": "Hora pico de la tarde", "start": "17:30", "end": "20:00", "days": [0, 1, 2, 3, 4], "speed_factor": 0.55},
    ],
    "school": {"windows": [["06:45", "08:30"], ["12:45", "14:30"]], "days": [0, 1, 2, 3, 4], "speed_limit_kmh": 20, "zone_m": 150},
    "night": {"start": "23:00", "end": "05:00", "speed_factor": 1.15, "signals": "amarillo intermitente", "pedestrian_factor": 0.15},
    "pedestrians": {"base_probability": 0.30, "peak_factor": 2.0, "wait_s": [6, 14]},
}

# Dinámica del vehículo (metros y segundos simulados)
ACCEL_MS2 = 1.6              # aceleración cómoda
DECEL_MS2 = 3.0              # frenado normal
COMFORT_DECEL_MS2 = 2.0      # la curva de frenado se calcula con una desaceleración cómoda
LOOKAHEAD_M = 220.0          # a qué distancia «ve» las señales
STOP_MARGIN_M = 2.5          # se detiene antes de la línea
CROSSING_CAP_KMH = 35.0      # cruce sin peatones: pasa con precaución
BUMP_CAP_KMH = 10.0
POTHOLE_CAP_KMH = {"leve": 28.0, "medio": 20.0, "grande": 12.0}
FLASHING_CAP_KMH = 30.0      # semáforo intermitente de noche
YELLOW_S = 4.0
DEFAULT_SPEED_FACTOR = 1.0


def hhmm_to_s(text):
    hours, minutes = text.split(":")
    return int(hours) * 3600 + int(minutes) * 60


def s_to_hhmm(seconds):
    seconds = int(seconds) % 86400
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def in_window(tod_s, start, end):
    """¿La hora del día está entre start y end (HH:MM)? Soporta ventanas que cruzan la medianoche (23:00 → 05:00)."""
    a, b = hhmm_to_s(start), hhmm_to_s(end)
    return a <= tod_s < b if a <= b else tod_s >= a or tod_s < b


class Schedule:
    """Horarios que cambian el comportamiento: hora pico, zona escolar y noche."""

    def __init__(self, data=None):
        self.data = data or DEFAULT_SCHEDULE

    def rush(self, tod_s, weekday):
        for window in self.data["rush_hours"]:
            if weekday in window["days"] and in_window(tod_s, window["start"], window["end"]):
                return window
        return None

    def school_active(self, tod_s, weekday):
        school = self.data["school"]
        return weekday in school["days"] and any(in_window(tod_s, a, b) for a, b in school["windows"])

    def is_night(self, tod_s):
        night = self.data["night"]
        return in_window(tod_s, night["start"], night["end"])

    def speed_factor(self, tod_s, weekday):
        """Multiplicador de la velocidad de crucero: <1 en hora pico (tráfico), >1 de noche (calles libres)."""
        if self.is_night(tod_s):
            return float(self.data["night"]["speed_factor"])
        window = self.rush(tod_s, weekday)
        return float(window["speed_factor"]) if window else DEFAULT_SPEED_FACTOR

    def pedestrian_probability(self, tod_s, weekday):
        """Probabilidad de que haya peatones esperando en un cruce a esta hora."""
        cfg = self.data["pedestrians"]
        p = float(cfg["base_probability"])
        if self.is_night(tod_s):
            return p * float(self.data["night"]["pedestrian_factor"])
        if self.rush(tod_s, weekday) or self.school_active(tod_s, weekday):
            p *= float(cfg["peak_factor"])
        return min(p, 0.95)

    def status(self, tod_s, weekday):
        """Texto del horario vigente, para mostrar en pantalla."""
        parts = []
        if self.is_night(tod_s):
            parts.append(f"Noche · semáforos en {self.data['night']['signals']} · calles más libres")
        window = self.rush(tod_s, weekday)
        if window:
            parts.append(f"{window['name']} · tráfico lento (×{window['speed_factor']:.2f})")
        if self.school_active(tod_s, weekday):
            parts.append(f"Horario escolar · zonas escolares a {self.data['school']['speed_limit_kmh']} km/h")
        return " · ".join(parts) if parts else "Horario normal"


@dataclass(frozen=True)
class Hazard:
    """Una señal vial sobre una ruta: `along_m` es la distancia desde el inicio del circuito."""
    id: str
    kind: str
    latitude: float
    longitude: float
    along_m: float
    source: str = "OpenStreetMap"      # o «simulado»
    name: str = ""
    props: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def label(self):
        return KINDS[self.kind]["label"]


def signal_state(hazard, tod_s, night=False):
    """Estado de un semáforo en un instante: 'green' | 'yellow' | 'red' | 'flash' (intermitente de noche).

    El ciclo se repite cada `cycle_s` segundos; el verde dura `green_s`, luego 4 s de amarillo y el resto rojo.
    `offset_s` desfasa cada semáforo para que no cambien todos a la vez."""
    if night:
        return "flash"
    cycle = float(hazard.props.get("cycle_s", 80))
    green = float(hazard.props.get("green_s", 38))
    phase = (tod_s + float(hazard.props.get("offset_s", 0))) % cycle
    if phase < green:
        return "green"
    return "yellow" if phase < green + YELLOW_S else "red"


def seconds_until_green(hazard, tod_s):
    cycle = float(hazard.props.get("cycle_s", 80))
    phase = (tod_s + float(hazard.props.get("offset_s", 0))) % cycle
    return 0.0 if phase < float(hazard.props.get("green_s", 38)) else cycle - phase


def braking_distance_m(speed_ms, decel=COMFORT_DECEL_MS2):
    return speed_ms * speed_ms / (2 * decel)


def speed_cap_at(distance_m, final_ms, decel=COMFORT_DECEL_MS2):
    """Velocidad máxima (m/s) a `distance_m` de un punto en el que se debe ir a `final_ms`: curva de frenado v = √(v_f² + 2·a·d)."""
    return math.sqrt(final_ms * final_ms + 2 * decel * max(distance_m, 0.0))


def hazards_from_collection(collection, route_name):
    """Señales de una ruta, ordenadas por distancia recorrida desde el inicio del circuito."""
    found = []
    for feature in collection.get("features", []):
        p = feature["properties"]
        if p.get("route") != route_name:
            continue
        lon, lat = feature["geometry"]["coordinates"]
        extra = {k: v for k, v in p.items() if k not in {"id", "kind", "source", "route", "along_m", "name"}}
        found.append(Hazard(id=p["id"], kind=p["kind"], latitude=lat, longitude=lon, along_m=float(p["along_m"]),
                            source=p.get("source", "OpenStreetMap"), name=p.get("name", ""), props=extra))
    return tuple(sorted(found, key=lambda h: h.along_m))
