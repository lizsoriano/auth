"""Simulación de vehículos sobre rutas de Monterrey. Sin dependencias: lo usan la GUI y el modo headless."""
import math
import random
from dataclasses import dataclass

DEFAULT_URL = "ws://localhost:5900/ws?role=gps"
EARTH_RADIUS_M = 6_371_000
MIN_SPEED_KMH = 15.0
MAX_SPEED_KMH = 80.0

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
    name: str
    points: tuple  # cada elemento: (nombre, lat, lon); la ruta es un circuito cerrado


ROUTES = (
    Route("Centro - Fundidora - Tec", (MACROPLAZA, FUNDIDORA, TEC)),
    Route("Corredor poniente", (MACROPLAZA, OBISPADO, SAN_PEDRO, SANTA_CATARINA)),
    Route("Oriente", (MACROPLAZA, GUADALUPE, ESTADIO, FUNDIDORA)),
    Route("Norte - Cumbres", (MACROPLAZA, NORTE, CUMBRES)),
)


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


class SimVehicle:
    """Recorre su circuito a velocidad variable; devuelve la posición en el formato del microservicio."""

    def __init__(self, vehicle_id, route, rng, start_fraction=0.0):
        self.vehicle_id = vehicle_id
        self.route = route
        self._rng = rng
        loop = list(route.points) + [route.points[0]]
        self._legs = [(a[1], a[2], b[1], b[2], haversine_m(a[1], a[2], b[1], b[2])) for a, b in zip(loop, loop[1:])]
        self.length_m = sum(leg[4] for leg in self._legs)
        self.distance_m = (start_fraction % 1.0) * self.length_m
        self.speed_kmh = rng.uniform(25, 55)

    def advance(self, seconds, time_scale=1.0):
        self.speed_kmh = min(MAX_SPEED_KMH, max(MIN_SPEED_KMH, self.speed_kmh + self._rng.uniform(-4, 4)))
        self.distance_m = (self.distance_m + self.speed_kmh / 3.6 * seconds * time_scale) % self.length_m
        return self.position()

    def position(self):
        remaining = self.distance_m
        for lat1, lon1, lat2, lon2, length in self._legs:
            if remaining <= length:
                fraction = remaining / length if length else 0.0
                return {
                    "vehicle_id": self.vehicle_id,
                    "latitude": round(lat1 + (lat2 - lat1) * fraction, 6),
                    "longitude": round(lon1 + (lon2 - lon1) * fraction, 6),
                    "speed": round(self.speed_kmh, 1),
                    "heading": round(bearing_deg(lat1, lon1, lat2, lon2), 1) % 360,
                }
            remaining -= length
        lat, lon = self._legs[-1][2], self._legs[-1][3]
        return {"vehicle_id": self.vehicle_id, "latitude": lat, "longitude": lon,
                "speed": round(self.speed_kmh, 1), "heading": 0.0}


class Fleet:
    """Flota de n vehículos repartidos sobre las rutas, escalonados para que no vayan juntos."""

    def __init__(self, count, seed=None, time_scale=5.0):
        if count < 1:
            raise ValueError("La flota necesita al menos un vehículo")
        rng = random.Random(seed)
        self.time_scale = time_scale
        self.vehicles = [
            SimVehicle(f"V{index + 1:03d}", ROUTES[index % len(ROUTES)], rng,
                       start_fraction=(index // len(ROUTES)) * 0.37 + rng.uniform(0, 0.2))
            for index in range(count)
        ]

    def step(self, seconds):
        return [vehicle.advance(seconds, self.time_scale) for vehicle in self.vehicles]

    def positions(self):
        return [vehicle.position() for vehicle in self.vehicles]
