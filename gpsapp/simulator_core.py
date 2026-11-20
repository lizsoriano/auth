"""Simulación de vehículos sobre rutas de Monterrey. Sin dependencias: lo usan la GUI y el modo headless.

Los vehículos siguen rutas REALES por las calles (GeoJSON calculado con OSRM sobre OpenStreetMap, ver routing.py).
Si el archivo `data/rutas_monterrey.geojson` no existe, usan los circuitos antiguos en línea recta entre puntos.

Sobre esas rutas hay señales viales (semáforos, cruces peatonales, altos, topes, zonas escolares de OpenStreetMap y baches
simulados, ver hazards.py) y horarios (hora pico, horario escolar, noche, ver traffic.py): el vehículo frena, se detiene,
espera y vuelve a acelerar, así que su velocidad baja hasta 0 y la velocidad promedio ya incluye las paradas.
"""
import bisect
import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import accumulate
from pathlib import Path

from traffic import (ACCEL_MS2, BUMP_CAP_KMH, CROSSING_CAP_KMH, DECEL_MS2, FLASHING_CAP_KMH, LOOKAHEAD_M, POTHOLE_CAP_KMH,
                     STOP_MARGIN_M, Schedule, hazards_from_collection, signal_state, speed_cap_at)

DEFAULT_URL = "ws://localhost:5900/ws?role=gps"
ROUTES_FILE = Path(__file__).resolve().parent / "data" / "rutas_monterrey.geojson"
HAZARDS_FILE = Path(__file__).resolve().parent / "data" / "senales_viales.geojson"
EARTH_RADIUS_M = 6_371_000
MIN_SPEED_KMH = 15.0      # velocidad de crucero mínima (la real baja a 0 en un semáforo en rojo)
MAX_SPEED_KMH = 80.0
DEFAULT_CRUISE_KMH = 40.0
SUBSTEP_S = 1.0           # los eventos se evalúan cada segundo simulado
SCAN_BEHIND_M = 160.0     # también se miran las señales recién pasadas (zonas escolares son largas)
MONTERREY_UTC_OFFSET = timezone(timedelta(hours=-6))   # sin horario de verano desde 2022

# Puntos de referencia reales de la zona metropolitana: (nombre, latitud, longitud).
MACROPLAZA = ("Macroplaza", 25.6700, -100.3090)
FUNDIDORA = ("Parque Fundidora", 25.6780, -100.2840)
TEC = ("Tec de Monterrey", 25.6514, -100.2895)
OBISPADO = ("Obispado", 25.6722, -100.3457)
SAN_PEDRO = ("San Pedro Garza García", 25.6573, -100.4021)
SANTA_CATARINA = ("Santa Catarina", 25.6733, -100.4586)
GUADALUPE = ("Guadalupe", 25.6768, -100.2561)
ESTADIO = ("Estadio BBVA", 25.6693, -100.2444)
CUMBRES = ("Cumbres", 25.7180, -100.3740)
NORTE = ("Colonia Mitras Norte", 25.6950, -100.3200)


@dataclass(frozen=True)
class Route:
    """Circuito. `points` = vértices (nombre, lat, lon). Con `closed` el último vértice ya es el primero."""
    name: str
    points: tuple
    streets: tuple = ()      # calle de cada tramo (entre un vértice y el siguiente); vacío = se desconoce
    leg_speeds: tuple = ()   # velocidad típica (km/h) de cada tramo según OpenStreetMap; None = sin dato
    closed: bool = False
    landmarks: tuple = ()    # puntos de paso con nombre (para etiquetar el mapa)

    def vertices(self):
        pts = list(self.points)
        return pts if self.closed else pts + [pts[0]]

    def legs(self):
        """Tramos como (lat1, lon1, lat2, lon2, longitud_m)."""
        verts = self.vertices()
        return [(a[1], a[2], b[1], b[2], haversine_m(a[1], a[2], b[1], b[2])) for a, b in zip(verts, verts[1:])]

    def length_m(self):
        return sum(leg[4] for leg in self.legs())

    @classmethod
    def from_feature(cls, feature):
        """Ruta a partir de un Feature GeoJSON LineString (coordenadas [lon, lat]) con properties.segments."""
        geometry = feature["geometry"]
        if geometry.get("type") != "LineString" or len(geometry["coordinates"]) < 2:
            raise ValueError("La ruta debe ser un LineString con al menos 2 vértices")
        coords = geometry["coordinates"]
        legs = len(coords) - 1
        streets, speeds = [""] * legs, [None] * legs
        for segment in feature.get("properties", {}).get("segments", []):
            for index in range(int(segment["start"]), min(int(segment["end"]), legs)):
                streets[index] = segment.get("street") or ""
                speeds[index] = segment.get("speed_kmh")
        props = feature.get("properties", {})
        landmarks = tuple((w["name"], w["latitude"], w["longitude"]) for w in props.get("waypoints", []))
        return cls(name=props.get("name", "Ruta"), points=tuple(("", lat, lon) for lon, lat in coords),
                   streets=tuple(streets), leg_speeds=tuple(speeds), closed=list(coords[0]) == list(coords[-1]),
                   landmarks=landmarks)


ROUTES = (
    Route("Centro - Fundidora - Tec", (MACROPLAZA, FUNDIDORA, TEC)),
    Route("Corredor poniente", (MACROPLAZA, OBISPADO, SAN_PEDRO, SANTA_CATARINA)),
    Route("Oriente", (MACROPLAZA, GUADALUPE, ESTADIO, FUNDIDORA)),
    Route("Norte - Cumbres", (MACROPLAZA, NORTE, CUMBRES)),
)


def default_routes(path=ROUTES_FILE):
    """Rutas reales por las calles (GeoJSON) si el archivo existe y es válido; si no, los circuitos en línea recta."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        routes = tuple(Route.from_feature(feature) for feature in data["features"])
        return routes or ROUTES
    except (OSError, ValueError, KeyError, TypeError):
        return ROUTES


def load_hazards(path=HAZARDS_FILE):
    """FeatureCollection de señales viales (hazards.py), o None si no existe o no es válido."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data.get("features"), list) else None
    except (OSError, ValueError, AttributeError):
        return None


def hazards_for_route(collection, route):
    """Señales de una ruta; vacío si el archivo se calculó sobre otro trazado (la distancia recorrida no coincidiría)."""
    if not collection:
        return ()
    expected = (collection.get("routes") or {}).get(route.name)
    if expected is None or abs(float(expected) - route.length_m()) > 5.0:
        return ()
    return hazards_from_collection(collection, route.name)


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Rumbo inicial de 0 (norte) a 360 (exclusivo), en sentido horario."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def average_speed_kmh(distance_m, seconds):
    """Velocidad promedio = distancia total recorrida / tiempo total empleado  (v̄ = Σd / Σt).

    NO es el promedio de las velocidades instantáneas: un vehículo que recorre 1 km a 20 km/h y otro 1 km a 60 km/h
    promedia 30 km/h (2 km en 4 min), no 40. De m/s a km/h se multiplica por 3.6.
    """
    if seconds <= 0 or distance_m < 0:
        return 0.0
    return distance_m / seconds * 3.6


class SimClock:
    """Hora del día (y día de la semana) de la simulación; avanza con el tiempo simulado. Por defecto, la hora de Monterrey."""

    def __init__(self, tod_s=None, weekday=None, schedule=None):
        now = datetime.now(MONTERREY_UTC_OFFSET)
        self.tod_s = float(now.hour * 3600 + now.minute * 60 + now.second) if tod_s is None else float(tod_s) % 86400
        self.weekday = now.weekday() if weekday is None else int(weekday) % 7
        self.schedule = schedule or Schedule()

    def tick(self, seconds):
        total = self.tod_s + seconds
        self.weekday = (self.weekday + int(total // 86400)) % 7
        self.tod_s = total % 86400

    @property
    def text(self):
        seconds = int(self.tod_s)
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"

    @property
    def full_text(self):
        seconds = int(self.tod_s)
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"

    def status(self):
        return self.schedule.status(self.tod_s, self.weekday)


SIGNAL_NAMES = {"red": "rojo", "yellow": "amarillo", "green": "verde", "flash": "intermitente"}


class SimVehicle:
    """Recorre su circuito a la velocidad típica de cada calle (con variación y tráfico según el horario), frena y se detiene
    ante semáforos en rojo, peatones, altos, topes, baches y zonas escolares; devuelve la posición del contrato."""

    def __init__(self, vehicle_id, route, rng, start_fraction=0.0, hazards=(), clock=None):
        self.vehicle_id = vehicle_id
        self.route = route
        self._rng = rng
        self._legs = route.legs()
        self._ends = list(accumulate(leg[4] for leg in self._legs))  # distancia acumulada al final de cada tramo
        self.length_m = self._ends[-1]
        self.distance_m = (start_fraction % 1.0) * self.length_m
        self.speed_kmh = rng.uniform(25, 55)
        self.trip_distance_m = 0.0   # lo recorrido desde que arrancó (no se reinicia al dar la vuelta)
        self.trip_time_s = 0.0       # tiempo simulado transcurrido (incluye las paradas)
        self.hazards = tuple(hazards)
        self._along = [h.along_m for h in self.hazards]
        self._own_clock = clock is None
        self.clock = clock or SimClock()
        self._noise = 0.0
        self._committed = set()      # semáforos ante los que ya decidió detenerse (hasta que se ponga verde)
        self._waits = {}             # peatones / alto: segundos que aún debe esperar en cada punto
        self.event, self.event_text = "clear", "Circulando con fluidez"

    def _leg_index(self):
        return min(bisect.bisect_left(self._ends, self.distance_m), len(self._legs) - 1)

    def _target_speed(self, leg):
        speeds = self.route.leg_speeds
        value = speeds[leg] if leg < len(speeds) else None
        return None if value is None else float(value)

    def advance(self, seconds, time_scale=1.0):
        total = seconds * time_scale
        steps = max(1, math.ceil(total / SUBSTEP_S))
        dt = total / steps
        base = self.clock.tod_s
        for index in range(steps):
            self._substep(dt, (base + index * dt) % 86400)
        self.trip_time_s += total
        if self._own_clock:
            self.clock.tick(total)
        return self.position()

    # ---- un paso de ~1 s simulado
    def _substep(self, dt, tod):
        schedule, weekday = self.clock.schedule, self.clock.weekday
        factor = schedule.speed_factor(tod, weekday)
        target = self._target_speed(self._leg_index())
        self._noise = max(-4.0, min(4.0, self._noise + self._rng.uniform(-1.0, 1.0)))
        cruise_kmh = (DEFAULT_CRUISE_KMH if target is None else target) * factor + self._noise
        cruise = min(MAX_SPEED_KMH, max(MIN_SPEED_KMH, cruise_kmh)) / 3.6
        speed = self.speed_kmh / 3.6
        limit, info, stop_gap = self._hazard_limit(speed, tod, dt)
        desired = min(cruise, limit)
        new = min(desired, speed + ACCEL_MS2 * dt) if desired >= speed else max(desired, speed - DECEL_MS2 * dt)
        moved = (speed + new) / 2 * dt
        if stop_gap is not None and moved >= stop_gap:      # nunca cruza la línea de alto mientras deba detenerse
            moved, new = max(stop_gap, 0.0), 0.0
        self.speed_kmh = new * 3.6
        self.distance_m = (self.distance_m + moved) % self.length_m
        self.trip_distance_m += moved
        if info is not None and (info[0] < cruise - 0.5 or info[0] == 0.0):
            self.event, self.event_text = info[1], info[2]
        elif schedule.is_night(tod):
            self.event, self.event_text = "night", "Noche · calles más libres"
        elif factor < 1.0:
            self.event, self.event_text = "rush", "Hora pico · tráfico lento"
        else:
            self.event, self.event_text = "clear", "Circulando con fluidez"

    def _hazard_limit(self, speed, tod, dt):
        """(velocidad máxima en m/s por las señales que tiene adelante, (cap, evento, texto) de la más restrictiva,
        distancia hasta la línea de alto si debe detenerse o None)."""
        if not self.hazards:
            return math.inf, None, None
        schedule, weekday, cycle = self.clock.schedule, self.clock.weekday, self.length_m
        night = schedule.is_night(tod)
        limit, info, stop_gap = math.inf, None, None
        count = len(self.hazards)
        first = bisect.bisect_left(self._along, (self.distance_m - SCAN_BEHIND_M) % cycle)
        for step in range(count):
            hazard = self.hazards[(first + step) % count]
            rel = ((hazard.along_m - self.distance_m + cycle / 2) % cycle) - cycle / 2   # >0: adelante, <0: ya pasó
            if rel > LOOKAHEAD_M + 200.0:
                break
            cap, kind, text, stop = math.inf, hazard.kind, "", None
            if hazard.kind == "school":
                cap, text = self._school_cap(hazard, rel, tod, weekday)
            elif rel < 0 or rel > LOOKAHEAD_M:
                self._committed.discard(hazard.id)
                if rel < -30.0:
                    self._waits.pop(hazard.id, None)
                continue
            elif hazard.kind == "traffic_signals":
                cap, text, stop = self._signal_cap(hazard, rel, speed, tod, night)
            elif hazard.kind in ("crossing", "stop"):
                cap, text, stop = self._wait_cap(hazard, rel, speed, tod, dt)
            elif hazard.kind == "bump":
                cap, text = speed_cap_at(rel, BUMP_CAP_KMH / 3.6), f"Tope a {rel:.0f} m · reduciendo"
            elif hazard.kind == "pothole":
                severity = hazard.props.get("severity", "leve")
                cap = speed_cap_at(rel, POTHOLE_CAP_KMH.get(severity, 28.0) / 3.6)
                text = f"Bache {severity} a {rel:.0f} m · esquivando"
            if stop is not None:
                stop_gap = stop if stop_gap is None else min(stop_gap, stop)
            if cap < limit:
                limit = cap
            if text and (info is None or cap < info[0]):
                info = (cap, kind, text)
        return limit, info, stop_gap

    def _school_cap(self, hazard, rel, tod, weekday):
        schedule = self.clock.schedule
        if not schedule.school_active(tod, weekday):
            return math.inf, ""
        zone = float(hazard.props.get("zone_m", schedule.data["school"]["zone_m"]))
        limit = float(schedule.data["school"]["speed_limit_kmh"]) / 3.6
        if abs(rel) <= zone:
            return limit, f"Zona escolar · máximo {limit * 3.6:.0f} km/h"
        if 0 < rel - zone <= LOOKAHEAD_M:
            return speed_cap_at(rel - zone, limit), f"Zona escolar a {rel - zone:.0f} m · reduciendo"
        return math.inf, ""

    def _signal_cap(self, hazard, rel, speed, tod, night):
        if night:   # de noche los semáforos parpadean en amarillo: se pasa con precaución
            return speed_cap_at(rel, FLASHING_CAP_KMH / 3.6), f"Semáforo intermitente a {rel:.0f} m · precaución", None
        now = signal_state(hazard, tod)
        arrival = signal_state(hazard, tod + rel / max(speed, 3.0))
        can_stop = rel > speed * speed / (2 * DECEL_MS2) + 1.0
        if hazard.id in self._committed:
            must_stop = now != "green"
        else:
            must_stop = can_stop and (now != "green" or arrival == "red")
        if not must_stop:
            self._committed.discard(hazard.id)
            return math.inf, "", None
        self._committed.add(hazard.id)
        gap = rel - STOP_MARGIN_M
        name = SIGNAL_NAMES[now if now != "green" else arrival]
        waiting = gap <= 0.5 and speed < 0.5
        text = f"Esperando semáforo en {name}" if waiting else f"Frenando: semáforo en {name} a {rel:.0f} m"
        return speed_cap_at(max(gap, 0.0), 0.0), text, gap

    def _wait_cap(self, hazard, rel, speed, tod, dt):
        """Cruce peatonal (a veces hay peatones) y alto (siempre se detiene unos segundos)."""
        schedule, weekday = self.clock.schedule, self.clock.weekday
        if hazard.id not in self._waits:
            if hazard.kind == "stop":
                self._waits[hazard.id] = self._rng.uniform(2.0, 4.0)
            elif self._rng.random() < schedule.pedestrian_probability(tod, weekday):
                low, high = schedule.data["pedestrians"]["wait_s"]
                self._waits[hazard.id] = self._rng.uniform(low, high)
            else:
                self._waits[hazard.id] = 0.0
        remaining = self._waits[hazard.id]
        if remaining <= 0:
            if hazard.kind == "stop":
                return math.inf, "", None
            return speed_cap_at(rel, CROSSING_CAP_KMH / 3.6), f"Cruce peatonal a {rel:.0f} m · precaución", None
        gap = rel - STOP_MARGIN_M
        waiting = gap <= 0.5 and speed < 0.5
        if waiting:
            self._waits[hazard.id] = remaining - dt
        if hazard.kind == "stop":
            text = "Detenido en el alto" if waiting else f"Frenando: alto a {rel:.0f} m"
        else:
            text = "Cediendo el paso a peatones" if waiting else f"Frenando: peatones en el cruce a {rel:.0f} m"
        return speed_cap_at(max(gap, 0.0), 0.0), text, gap

    @property
    def avg_speed_kmh(self):
        return average_speed_kmh(self.trip_distance_m, self.trip_time_s)

    def street(self):
        streets = self.route.streets
        leg = self._leg_index()
        return streets[leg] if leg < len(streets) else ""

    def position(self):
        leg = self._leg_index()
        lat1, lon1, lat2, lon2, length = self._legs[leg]
        before = self._ends[leg - 1] if leg else 0.0
        fraction = min(1.0, max(0.0, (self.distance_m - before) / length)) if length else 0.0
        payload = {
            "vehicle_id": self.vehicle_id,
            "latitude": round(lat1 + (lat2 - lat1) * fraction, 6),
            "longitude": round(lon1 + (lon2 - lon1) * fraction, 6),
            "speed": round(self.speed_kmh, 1),
            "heading": round(bearing_deg(lat1, lon1, lat2, lon2), 1) % 360 if length else 0.0,
            "avg_speed": round(self.avg_speed_kmh, 1),
            "trip_distance_m": round(self.trip_distance_m, 1),
            "trip_time_s": round(self.trip_time_s, 1),
            "event": self.event,
            "event_text": self.event_text,
            "sim_time": self.clock.full_text,
            "sim_day": self.clock.weekday,
        }
        street = self.street()
        if street:
            payload["street"] = street
        return payload


MAX_BATCH = 100   # el microservicio acepta hasta 100 posiciones por mensaje


def batches(items, size=MAX_BATCH):
    """Parte una lista de posiciones en lotes: un mensaje por lote en vez de uno por vehículo (escala a cientos)."""
    for start in range(0, len(items), size):
        yield items[start:start + size]


class Fleet:
    """Flota de n vehículos repartidos de forma pareja sobre las rutas (rotan por ruta y se escalonan en cada una).

    Con 3 vehículos, cada uno va por una ruta distinta; con 100, unos 25 por ruta separados a lo largo del circuito.
    `hazards`: señales viales (None = las del archivo `data/senales_viales.geojson`; False = sin señales).
    `start_time` ("HH:MM") y `weekday` (0 = lunes) fijan el horario de inicio; por omisión, la hora actual de Monterrey.
    """

    def __init__(self, count, seed=None, time_scale=5.0, routes=None, hazards=None, start_time=None, weekday=None):
        if count < 1:
            raise ValueError("La flota necesita al menos un vehículo")
        rng = random.Random(seed)
        self.time_scale = time_scale
        self.routes = tuple(routes) if routes else default_routes()
        self.hazard_collection = load_hazards() if hazards is None else (hazards or None)
        schedule = Schedule((self.hazard_collection or {}).get("schedule")) if self.hazard_collection else Schedule()
        tod = None
        if start_time is not None:
            hours, minutes = start_time.split(":")
            tod = int(hours) * 3600 + int(minutes) * 60
        self.clock = SimClock(tod, weekday, schedule)
        by_route = {route.name: hazards_for_route(self.hazard_collection, route) for route in self.routes}
        per_route = -(-count // len(self.routes))   # vehículos por ruta, redondeando hacia arriba
        self.vehicles = [
            SimVehicle(f"V{index + 1:03d}", self.routes[index % len(self.routes)], rng,
                       start_fraction=((index // len(self.routes)) + rng.uniform(0, 0.4)) / per_route,
                       hazards=by_route[self.routes[index % len(self.routes)].name], clock=self.clock)
            for index in range(count)
        ]

    def step(self, seconds):
        positions = [vehicle.advance(seconds, self.time_scale) for vehicle in self.vehicles]
        self.clock.tick(seconds * self.time_scale)
        return positions

    def positions(self):
        return [vehicle.position() for vehicle in self.vehicles]
