"""Rutas REALES por las calles de Monterrey, en formato GeoJSON.

Usa OSRM (https://project-osrm.org), un motor de rutas gratuito que trabaja con los datos de OpenStreetMap:
dados unos puntos de paso, devuelve el recorrido por las calles (una geometría GeoJSON `LineString`), la distancia,
el tiempo estimado y, por cada tramo, el NOMBRE DE LA CALLE y su velocidad típica.

El servidor público de OSRM es una demostración con uso moderado, así que las rutas se piden UNA vez, se guardan en
`data/rutas_monterrey.geojson` y la simulación lee ese archivo (funciona sin internet y sin saturar el servicio):

    python routing.py --refresh            # vuelve a pedir las 4 rutas y reescribe los archivos GeoJSON

Datos © colaboradores de OpenStreetMap (licencia ODbL): https://www.openstreetmap.org/copyright
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from simulator_core import ROUTES, haversine_m

OSRM_URL = "https://router.project-osrm.org"
USER_AGENT = "library-gpsapp/1.0 (proyecto escolar UDEM; ruth.soriano@udem.edu)"
DATA_FILE = Path(__file__).resolve().parent / "data" / "rutas_monterrey.geojson"
# El microservicio sirve la MISMA ruta a los mapas; si existe la carpeta hermana, --refresh escribe ahí también.
SERVICE_DATA_FILE = Path(__file__).resolve().parents[1] / "services" / "gps" / "gps_service" / "data" / "rutas_monterrey.geojson"
ATTRIBUTION = "© colaboradores de OpenStreetMap (ODbL) · rutas calculadas con OSRM"
UNNAMED = "Vía sin nombre"
PAUSE_BETWEEN_REQUESTS_S = 1.5  # cortesía con el servidor público


class RoutingError(RuntimeError):
    """OSRM no pudo calcular la ruta (sin conexión, sin camino, respuesta inesperada)."""


def osrm_url(waypoints, base_url=OSRM_URL):
    """URL de una ruta que pasa por los puntos (nombre, lat, lon); OSRM espera lon,lat."""
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for _name, lat, lon in waypoints)
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson", "steps": "true",
                                    "continue_straight": "false"})
    return f"{base_url}/route/v1/driving/{coords}?{query}"


def http_get_json(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RoutingError(f"No se pudo consultar OSRM: {exc}") from exc


STREET_MAX = 110


def label_unnamed(segments):
    """Los enlaces, retornos y accesos suelen no tener nombre en OpenStreetMap. En vez de «Vía sin nombre» se
    describen con las calles con nombre que los rodean: «Enlace Avenida A → Avenida B» (o «Enlace de Avenida A»)."""
    named = [i for i, seg in enumerate(segments) if seg["street"] != UNNAMED]
    for i, seg in enumerate(segments):
        if seg["street"] != UNNAMED or not named:
            continue
        before = next((segments[j]["street"] for j in reversed(named) if j < i), None)
        after = next((segments[j]["street"] for j in named if j > i), None)
        if before and after and before != after:
            label = f"Enlace {before} → {after}"
        elif before or after:
            label = f"Enlace de {before or after}"
        else:
            continue
        seg["street"] = label if len(label) <= STREET_MAX else label[:STREET_MAX - 1] + "…"


def route_to_feature(name, waypoints, osrm):
    """Convierte la respuesta de OSRM en un Feature GeoJSON (LineString) con la calle de cada tramo."""
    if not isinstance(osrm, dict) or osrm.get("code") != "Ok" or not osrm.get("routes"):
        raise RoutingError(f"OSRM no devolvió ruta para «{name}»: {osrm.get('code') if isinstance(osrm, dict) else osrm!r}")
    route = osrm["routes"][0]
    coordinates, segments = [], []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            geometry = step.get("geometry", {}).get("coordinates", [])
            start = max(len(coordinates) - 1, 0)
            added = 0
            for point in geometry:
                if coordinates and list(coordinates[-1]) == list(point):
                    continue  # vértice repetido (empalme entre pasos, o el paso «llegaste», que no tiene recorrido)
                coordinates.append(point)
                added += 1
            if not added:
                continue
            duration = float(step.get("duration") or 0)
            distance = float(step.get("distance") or 0)
            segments.append({
                "street": step.get("name") or step.get("ref") or UNNAMED,
                "start": start,
                "end": len(coordinates) - 1,
                "distance_m": round(distance, 1),
                "speed_kmh": round(distance / duration * 3.6, 1) if duration > 0 else None,
            })
    if len(coordinates) < 2:
        raise RoutingError(f"La ruta «{name}» llegó sin geometría")
    label_unnamed(segments)
    return {
        "type": "Feature",
        "properties": {
            "name": name,
            "distance_m": round(float(route["distance"]), 1),
            "duration_s": round(float(route["duration"]), 1),
            "vertices": len(coordinates),
            "waypoints": [{"name": n, "latitude": lat, "longitude": lon} for n, lat, lon in waypoints],
            "segments": segments,
            "source": "OSRM",
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def build_feature_collection(routes=ROUTES, fetch=http_get_json, pause=PAUSE_BETWEEN_REQUESTS_S, base_url=OSRM_URL):
    """Pide a OSRM el circuito cerrado de cada ruta (último punto = primero) y arma el FeatureCollection."""
    features = []
    for index, route in enumerate(routes):
        if index and pause:
            time.sleep(pause)
        circuit = list(route.points) + [route.points[0]]
        osrm = fetch(osrm_url(circuit, base_url))
        features.append(route_to_feature(route.name, list(route.points), osrm))
    return {"type": "FeatureCollection", "name": "rutas_monterrey", "attribution": ATTRIBUTION, "features": features}


def save_geojson(collection, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def load_geojson(path=DATA_FILE):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def track_distance_m(feature):
    """Longitud real de la ruta sumando las distancias haversine entre sus vértices (GeoJSON es [lon, lat])."""
    coords = feature["geometry"]["coordinates"]
    return sum(haversine_m(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Descarga de OSRM/OpenStreetMap las rutas por las calles de Monterrey")
    parser.add_argument("--refresh", action="store_true", help="pide las rutas a OSRM y reescribe los GeoJSON")
    parser.add_argument("--output", default=str(DATA_FILE), help="archivo de salida")
    args = parser.parse_args(argv)
    if not args.refresh:
        parser.print_help()
        return 0
    collection = build_feature_collection()
    targets = [Path(args.output)]
    if SERVICE_DATA_FILE.parent.parent.exists() and SERVICE_DATA_FILE not in targets:
        targets.append(SERVICE_DATA_FILE)
    for target in targets:
        save_geojson(collection, target)
        print("escrito:", target)
    for feature in collection["features"]:
        p = feature["properties"]
        print(f'  {p["name"]}: {p["distance_m"] / 1000:.1f} km · {p["duration_s"] / 60:.0f} min · {p["vertices"]} vértices · '
              f'{len({s["street"] for s in p["segments"]})} calles')
    return 0


if __name__ == "__main__":
    sys.exit(main())
