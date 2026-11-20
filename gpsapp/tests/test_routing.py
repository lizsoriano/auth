import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routing  # noqa: E402
from simulator_core import ROUTES  # noqa: E402

WAYPOINTS = [("A", 25.0, -100.0), ("B", 25.1, -100.1), ("C", 25.2, -100.2)]


def osrm_response(code="Ok"):
    """Respuesta mínima de OSRM: 2 tramos (legs); el segundo paso arranca donde terminó el anterior."""
    return {"code": code, "routes": [{"distance": 3000.0, "duration": 300.0, "legs": [
        {"steps": [
            {"name": "Avenida Constitución", "ref": "", "distance": 1000.0, "duration": 60.0,
             "geometry": {"type": "LineString", "coordinates": [[-100.0, 25.0], [-100.0, 25.01], [-100.01, 25.01]]}},
            {"name": "", "ref": "MX-85", "distance": 1000.0, "duration": 100.0,
             "geometry": {"type": "LineString", "coordinates": [[-100.01, 25.01], [-100.02, 25.02]]}},
            {"name": "", "ref": "", "distance": 0.0, "duration": 0.0,
             "geometry": {"type": "LineString", "coordinates": [[-100.02, 25.02], [-100.02, 25.02]]}},
        ]},
        {"steps": [
            {"name": "Calle Zuazua", "distance": 1000.0, "duration": 0.0,
             "geometry": {"type": "LineString", "coordinates": [[-100.02, 25.02], [-100.0, 25.0]]}},
            {"name": "", "distance": 0.0, "duration": 0.0, "geometry": {"type": "LineString", "coordinates": [[-100.0, 25.0]]}},
        ]},
    ]}]}


def test_osrm_url_uses_lon_lat_order_and_asks_for_geojson_with_street_steps():
    url = routing.osrm_url(WAYPOINTS)
    assert "/route/v1/driving/-100.000000,25.000000;-100.100000,25.100000;-100.200000,25.200000?" in url
    assert "geometries=geojson" in url and "steps=true" in url and "overview=full" in url


def test_route_to_feature_builds_a_linestring_with_street_names_and_speeds():
    feature = routing.route_to_feature("Prueba", WAYPOINTS, osrm_response())
    assert feature["type"] == "Feature" and feature["geometry"]["type"] == "LineString"
    coords = feature["geometry"]["coordinates"]
    assert coords == [[-100.0, 25.0], [-100.0, 25.01], [-100.01, 25.01], [-100.02, 25.02], [-100.0, 25.0]]  # sin vértices repetidos
    assert [(s["street"], s["start"], s["end"]) for s in feature["properties"]["segments"]] == [
        ("Avenida Constitución", 0, 2), ("MX-85", 2, 3), ("Calle Zuazua", 3, 4)]   # sin nombre → ref; paso final descartado
    assert feature["properties"]["segments"][0]["speed_kmh"] == pytest.approx(60.0)   # 1000 m en 60 s
    assert feature["properties"]["segments"][2]["speed_kmh"] is None                  # duración 0: sin dato
    assert feature["properties"]["distance_m"] == 3000.0 and feature["properties"]["vertices"] == 5
    assert [w["name"] for w in feature["properties"]["waypoints"]] == ["A", "B", "C"]


def test_unnamed_street_is_described_by_the_named_streets_around_it():
    osrm = osrm_response()
    osrm["routes"][0]["legs"][0]["steps"][1]["ref"] = ""
    feature = routing.route_to_feature("Prueba", WAYPOINTS, osrm)
    assert feature["properties"]["segments"][1]["street"] == "Enlace Avenida Constitución → Calle Zuazua"


def test_label_unnamed_handles_edges_and_long_names():
    unnamed = routing.UNNAMED
    only_before = [{"street": "Calle A"}, {"street": unnamed}]
    routing.label_unnamed(only_before)
    assert only_before[1]["street"] == "Enlace de Calle A"
    same_both_sides = [{"street": "Calle A"}, {"street": unnamed}, {"street": "Calle A"}]
    routing.label_unnamed(same_both_sides)
    assert same_both_sides[1]["street"] == "Enlace de Calle A"
    nothing_named = [{"street": unnamed}, {"street": unnamed}]
    routing.label_unnamed(nothing_named)
    assert [seg["street"] for seg in nothing_named] == [unnamed, unnamed]
    long = [{"street": "A" * 80}, {"street": unnamed}, {"street": "B" * 80}]
    routing.label_unnamed(long)
    assert len(long[1]["street"]) <= 120 and long[1]["street"].endswith("…")


@pytest.mark.parametrize("bad", [{"code": "NoRoute"}, {"code": "Ok", "routes": []}, "texto", None])
def test_route_to_feature_rejects_responses_without_a_route(bad):
    with pytest.raises(routing.RoutingError):
        routing.route_to_feature("Prueba", WAYPOINTS, bad)


def test_route_without_geometry_is_rejected():
    osrm = {"code": "Ok", "routes": [{"distance": 1, "duration": 1, "legs": [{"steps": []}]}]}
    with pytest.raises(routing.RoutingError):
        routing.route_to_feature("Vacía", WAYPOINTS, osrm)


def test_feature_collection_requests_each_circuit_closed_and_without_sleeping_in_tests():
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return osrm_response()

    collection = routing.build_feature_collection(ROUTES, fetch=fake_fetch, pause=0)
    assert collection["type"] == "FeatureCollection" and len(collection["features"]) == len(ROUTES) == len(urls)
    assert "OpenStreetMap" in collection["attribution"]
    first = ROUTES[0]
    coords = urls[0].split("/driving/")[1].split("?")[0].split(";")
    assert len(coords) == len(first.points) + 1 and coords[0] == coords[-1]     # circuito cerrado


def test_geojson_round_trip(tmp_path):
    collection = {"type": "FeatureCollection", "features": [routing.route_to_feature("Prueba", WAYPOINTS, osrm_response())]}
    target = tmp_path / "sub" / "rutas.geojson"
    routing.save_geojson(collection, target)
    assert routing.load_geojson(target) == collection


def test_network_errors_become_routing_errors(monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.URLError("sin red")
    monkeypatch.setattr(routing.urllib.request, "urlopen", boom)
    with pytest.raises(routing.RoutingError, match="No se pudo consultar OSRM"):
        routing.http_get_json("https://router.project-osrm.org/x")


# ------------------------------------------------- los GeoJSON incluidos
def test_shipped_geojson_is_valid_and_matches_osrm_distances():
    data = routing.load_geojson()
    assert data["type"] == "FeatureCollection" and "OpenStreetMap" in data["attribution"]
    assert [f["properties"]["name"] for f in data["features"]] == [r.name for r in ROUTES]
    for feature in data["features"]:
        coords = feature["geometry"]["coordinates"]
        assert coords[0] == coords[-1]                                              # circuito cerrado
        assert all(-101 < lon < -100 and 25 < lat < 26 for lon, lat in coords)      # dentro del área metropolitana
        assert routing.track_distance_m(feature) == pytest.approx(feature["properties"]["distance_m"], rel=0.02)
        assert all(0 <= s["start"] < s["end"] < len(coords) for s in feature["properties"]["segments"])


def test_service_serves_the_same_routes_as_the_simulator():
    if not routing.SERVICE_DATA_FILE.parent.exists():
        pytest.skip("la carpeta del microservicio no está junto al simulador")
    assert json.loads(routing.SERVICE_DATA_FILE.read_text(encoding="utf-8")) == routing.load_geojson()
