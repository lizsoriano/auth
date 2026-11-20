"""Señales viales sobre las rutas: semáforos, cruces peatonales, altos, topes y zonas escolares REALES de OpenStreetMap,
más baches SIMULADOS (OpenStreetMap no tiene baches).

Cómo se obtienen:
  1. Overpass API (gratuita) devuelve los elementos de OpenStreetMap del área de las rutas:
        highway=traffic_signals · highway=crossing · highway=stop · traffic_calming=bump|hump|… · amenity=school
  2. Cada elemento se «pega» a la ruta: se busca el punto más cercano del trazado y se guarda la distancia recorrida
     desde el inicio del circuito (`along_m`), que es lo que usa el simulador para saber qué hay adelante.
  3. Los baches se reparten con una semilla fija a lo largo de cada ruta y se marcan `source: simulado`.
  4. Todo se guarda en `data/senales_viales.geojson` (con los horarios): el simulador y el mapa leen el mismo archivo.

    python hazards.py --refresh      # vuelve a pedir los datos a Overpass (reintenta si el servidor está saturado)

Datos © colaboradores de OpenStreetMap (licencia ODbL): https://www.openstreetmap.org/copyright
"""
import argparse
import bisect
import json
import math
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

from simulator_core import default_routes
from traffic import DEFAULT_SCHEDULE, KINDS, POTHOLE_CAP_KMH

OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter")
USER_AGENT = "library-gpsapp/1.0 (proyecto escolar UDEM; ruth.soriano@udem.edu)"
DATA_FILE = Path(__file__).resolve().parent / "data" / "senales_viales.geojson"
SERVICE_DATA_FILE = Path(__file__).resolve().parents[1] / "services" / "gps" / "gps_service" / "data" / "senales_viales.geojson"
ATTRIBUTION = "© colaboradores de OpenStreetMap (ODbL) · baches simulados"
SIMULATED = "simulado"
OSM = "OpenStreetMap"
# A qué distancia máxima (m) del trazado cuenta una señal como «sobre la ruta».
SNAP_MAX_M = {"traffic_signals": 16.0, "crossing": 8.0, "stop": 8.0, "bump": 8.0, "school": 80.0}
BUMP_TAGS = {"bump", "hump", "table", "cushion", "rumble_strip"}
DEDUP_M = {"crossing": 15.0, "traffic_signals": 20.0, "bump": 10.0, "stop": 10.0, "school": 120.0}
POTHOLE_EVERY_M = 1500.0
CELL = 0.001   # ~110 m: tamaño de celda del índice espacial


class HazardsError(RuntimeError):
    """No se pudieron obtener las señales viales de OpenStreetMap."""


# ------------------------------------------------------------------ Overpass
def overpass_query(bbox):
    south, west, north, east = bbox
    return (f"[out:json][timeout:180][bbox:{south:.4f},{west:.4f},{north:.4f},{east:.4f}];"
            '(node["highway"="traffic_signals"];node["highway"="crossing"];node["highway"="stop"];'
            'node["traffic_calming"];nwr["amenity"="school"];);out center tags;')


def post_overpass(url, query, timeout=200):
    data = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_overpass(bbox, urls=OVERPASS_URLS, attempts=4, pause=25.0, post=post_overpass, sleep=time.sleep):
    """Pide los elementos; si el servidor público está saturado (502/504/tiempo agotado) reintenta con pausas."""
    query, errors = overpass_query(bbox), []
    for attempt in range(attempts):
        for url in urls:
            try:
                data = post(url, query)
                if isinstance(data, dict) and isinstance(data.get("elements"), list) and data["elements"]:
                    return data["elements"]
                errors.append(f"{url}: respuesta vacía")
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                errors.append(f"{url}: {exc}")
        if attempt < attempts - 1:
            sleep(pause)
    raise HazardsError("Overpass no respondió tras varios intentos: " + " | ".join(errors[-3:]))


def classify(element):
    """Tipo de señal de un elemento de OpenStreetMap, o None si no nos interesa."""
    tags = element.get("tags") or {}
    highway = tags.get("highway")
    if highway in ("traffic_signals", "crossing", "stop"):
        return highway
    if tags.get("traffic_calming") in BUMP_TAGS:
        return "bump"
    if tags.get("amenity") == "school":
        return "school"
    return None


def point_of(element):
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


# ----------------------------------------------- geometría de la ruta
class RouteGeometry:
    """Trazado de una ruta con índice espacial para encontrar rápido el punto más cercano y su distancia recorrida."""

    def __init__(self, route):
        self.vertices = [(p[1], p[2]) for p in route.vertices()]
        self.lat0 = sum(v[0] for v in self.vertices) / len(self.vertices)
        self.k = math.cos(math.radians(self.lat0))
        self.xy = [self._plane(lat, lon) for lat, lon in self.vertices]
        self.leg_len = [leg[4] for leg in route.legs()]          # los mismos largos (haversine) que usa el simulador
        self.cum = [0.0]
        for length in self.leg_len:
            self.cum.append(self.cum[-1] + length)
        self.length_m = self.cum[-1]
        self.grid = {}
        for index in range(len(self.leg_len)):
            (lat1, lon1), (lat2, lon2) = self.vertices[index], self.vertices[index + 1]
            for cx in range(int(min(lon1, lon2) // CELL) - 1, int(max(lon1, lon2) // CELL) + 2):
                for cy in range(int(min(lat1, lat2) // CELL) - 1, int(max(lat1, lat2) // CELL) + 2):
                    self.grid.setdefault((cx, cy), []).append(index)

    def _plane(self, lat, lon):
        return (lon * self.k * 111_320.0, lat * 110_540.0)

    def snap(self, lat, lon, max_m):
        """(distancia recorrida en m, distancia lateral en m) del punto más cercano al trazado, o None si está más lejos que max_m."""
        px, py = self._plane(lat, lon)
        best = None
        for index in self.grid.get((int(lon // CELL), int(lat // CELL)), ()):
            ax, ay = self.xy[index]
            bx, by = self.xy[index + 1]
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
            dist = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if dist <= max_m and (best is None or dist < best[0]):
                best = (dist, index, t)
        if best is None:
            return None
        dist, index, t = best
        return self.cum[index] + t * self.leg_len[index], dist

    def point_at(self, along_m):
        index = min(max(bisect.bisect_right(self.cum, along_m) - 1, 0), len(self.leg_len) - 1)
        t = (along_m - self.cum[index]) / self.leg_len[index] if self.leg_len[index] else 0.0
        (lat1, lon1), (lat2, lon2) = self.vertices[index], self.vertices[index + 1]
        return lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t


# --------------------------------------------------------- construcción
def signal_timing(osm_id, seed):
    """Ciclo del semáforo; sale del id de OpenStreetMap, así el mismo semáforo se comporta igual en todas las rutas."""
    rng = random.Random(zlib.crc32(str(osm_id).encode()) ^ seed)
    cycle = rng.choice((70, 80, 90, 100, 110))
    return {"cycle_s": cycle, "green_s": round(cycle * rng.uniform(0.42, 0.55)), "offset_s": round(rng.uniform(0, cycle))}


def bbox_of(routes, margin=0.01):
    lats = [p[1] for route in routes for p in route.points]
    lons = [p[2] for route in routes for p in route.points]
    return min(lats) - margin, min(lons) - margin, max(lats) + margin, max(lons) + margin


def _feature(hazard_id, kind, lat, lon, route_name, along, source, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {"id": hazard_id, "kind": kind, "label": KINDS[kind]["label"], "source": source, "route": route_name,
                           "along_m": round(along, 1), **props}}


def _dedup(features):
    """Quita señales repetidas: p. ej. los dos cruces de una avenida con camellón o dos nodos del mismo tope."""
    kept, last_along = [], {}
    for feature in sorted(features, key=lambda f: f["properties"]["along_m"]):
        p = feature["properties"]
        gap = DEDUP_M.get(p["kind"], 0.0)
        previous = last_along.get(p["kind"])
        if previous is not None and p["along_m"] - previous < gap:
            continue
        last_along[p["kind"]] = p["along_m"]
        kept.append(feature)
    return kept


def build_collection(routes, elements, seed=2026, schedule=None):
    """FeatureCollection de señales sobre las rutas: las de OpenStreetMap pegadas al trazado + baches simulados."""
    geometries = {route.name: RouteGeometry(route) for route in routes}
    per_route = {route.name: [] for route in routes}
    for element in elements:
        kind, point = classify(element), point_of(element)
        if kind is None or point is None:
            continue
        osm_id = f"{element.get('type', 'n')[0]}{element.get('id')}"
        name = (element.get("tags") or {}).get("name", "")
        extra = {"name": name} if name else {}
        if kind == "traffic_signals":
            extra.update(signal_timing(osm_id, seed))
        elif kind == "school":
            extra["zone_m"] = DEFAULT_SCHEDULE["school"]["zone_m"]
        elif kind == "bump":
            extra["calming"] = (element.get("tags") or {}).get("traffic_calming")
        for index, route in enumerate(routes):
            snapped = geometries[route.name].snap(point[0], point[1], SNAP_MAX_M[kind])
            if snapped:
                per_route[route.name].append(_feature(f"osm-{osm_id}@{index}", kind, point[0], point[1], route.name, snapped[0],
                                                      OSM, offset_m=round(snapped[1], 1), **extra))
    features = []
    for index, route in enumerate(routes):
        real = _dedup(per_route[route.name])
        rng = random.Random(seed + 1000 * (index + 1))
        geometry = geometries[route.name]
        count = max(1, int(geometry.length_m / POTHOLE_EVERY_M))
        for n in range(count):    # baches simulados: uno por cada ~1.5 km, lejos de otras señales
            along = (n + rng.uniform(0.2, 0.8)) * geometry.length_m / count
            if any(abs(f["properties"]["along_m"] - along) < 40 for f in real):
                continue
            lat, lon = geometry.point_at(along)
            severity = rng.choices(list(POTHOLE_CAP_KMH), weights=(5, 3.5, 1.5))[0]
            real.append(_feature(f"bache-{index}-{n}", "pothole", lat, lon, route.name, along, SIMULATED,
                                 severity=severity, offset_m=0.0))
        features.extend(sorted(real, key=lambda f: f["properties"]["along_m"]))
    counts = {}
    for feature in features:
        p = feature["properties"]
        counts.setdefault(p["kind"], {}).setdefault(p["source"], 0)
        counts[p["kind"]][p["source"]] += 1
    return {"type": "FeatureCollection", "name": "senales_viales", "attribution": ATTRIBUTION, "counts": counts,
            "routes": {name: round(geometry.length_m, 1) for name, geometry in geometries.items()},
            "schedule": schedule or DEFAULT_SCHEDULE, "features": features}


def save_geojson(collection, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def load_geojson(path=DATA_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Descarga de OpenStreetMap los semáforos, cruces, topes y escuelas de las rutas")
    parser.add_argument("--refresh", action="store_true", help="pide los datos a Overpass y reescribe los GeoJSON")
    parser.add_argument("--output", default=str(DATA_FILE))
    args = parser.parse_args(argv)
    if not args.refresh:
        parser.print_help()
        return 0
    routes = default_routes()
    elements = fetch_overpass(bbox_of(routes))
    print(f"Overpass devolvió {len(elements)} elementos")
    collection = build_collection(routes, elements)
    targets = [Path(args.output)]
    if SERVICE_DATA_FILE.parent.parent.exists() and SERVICE_DATA_FILE not in targets:
        targets.append(SERVICE_DATA_FILE)
    for target in targets:
        save_geojson(collection, target)
        print("escrito:", target)
    for kind, by_source in collection["counts"].items():
        print(f"  {KINDS[kind]['label']:15} {dict(by_source)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
