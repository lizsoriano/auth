import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator_core import (MAX_BATCH, MAX_SPEED_KMH, MIN_SPEED_KMH, ROUTES, Fleet, Route, SimVehicle,  # noqa: E402
                            average_speed_kmh, batches, bearing_deg, default_routes, haversine_m)

MONTERREY_BOX = (25.60, 25.75, -100.50, -100.20)
CONTRACT = {"vehicle_id", "latitude", "longitude", "speed", "heading", "avg_speed", "trip_distance_m", "trip_time_s"}


def test_haversine_matches_known_distance():
    # Macroplaza -> Parque Fundidora: unos 2.5 km en línea recta
    assert haversine_m(25.6700, -100.3090, 25.6780, -100.2840) == pytest.approx(2650, rel=0.05)


@pytest.mark.parametrize("target, expected", [
    ((26.0, -100.0), 0), ((25.0, -99.0), 90), ((24.0, -100.0), 180), ((25.0, -101.0), 270)])
def test_bearing_cardinal_directions(target, expected):
    origin = (25.0, -100.0)
    result = bearing_deg(*origin, *target)
    assert result == pytest.approx(expected, abs=1.0) or (expected == 0 and result > 359)


def test_every_route_is_a_loop_of_at_least_three_points():
    for route in ROUTES:
        assert len(route.points) >= 3


# ---------------------------------------------------- velocidad promedio
def test_average_speed_is_total_distance_over_total_time_not_the_mean_of_speeds():
    # 1 km a 20 km/h (180 s) + 1 km a 60 km/h (60 s) = 2 km en 240 s = 30 km/h; el promedio de velocidades daría 40
    assert average_speed_kmh(2000, 240) == pytest.approx(30.0)
    assert (20 + 60) / 2 == 40
    assert average_speed_kmh(1000, 100) == pytest.approx(36.0)   # 10 m/s = 36 km/h


@pytest.mark.parametrize("distance, seconds", [(0, 0), (500, 0), (500, -3), (-1, 10)])
def test_average_speed_without_valid_time_or_distance_is_zero(distance, seconds):
    assert average_speed_kmh(distance, seconds) == 0.0


def test_vehicle_average_speed_matches_trip_distance_over_trip_time():
    vehicle = SimVehicle("V001", default_routes()[0], random.Random(5))
    assert vehicle.position()["avg_speed"] == 0.0 and vehicle.position()["trip_time_s"] == 0.0
    for _ in range(200):
        position = vehicle.advance(2.0, time_scale=5.0)
    assert position["trip_time_s"] == pytest.approx(200 * 2.0 * 5.0)
    assert position["avg_speed"] == pytest.approx(position["trip_distance_m"] / position["trip_time_s"] * 3.6, abs=0.06)
    assert 0 < position["avg_speed"] <= MAX_SPEED_KMH


# ---------------------------------------------------------- flota y contrato
def test_fleet_positions_have_the_microservice_contract():
    fleet = Fleet(6, seed=1)
    for _ in range(50):
        for position in fleet.step(1.0):
            assert CONTRACT <= set(position) <= CONTRACT | {"street", "event", "event_text", "sim_time", "sim_day"}
            lat_min, lat_max, lon_min, lon_max = MONTERREY_BOX
            assert lat_min <= position["latitude"] <= lat_max
            assert lon_min <= position["longitude"] <= lon_max
            assert 0 <= position["speed"] <= MAX_SPEED_KMH      # puede ser 0: semáforo en rojo
            assert 0 <= position["heading"] < 360


def test_vehicle_ids_are_unique_and_valid_for_the_service():
    ids = [p["vehicle_id"] for p in Fleet(10, seed=2).positions()]
    assert len(set(ids)) == 10 and ids[0] == "V001"


def test_same_seed_gives_same_trip():
    a, b = Fleet(3, seed=7), Fleet(3, seed=7)
    assert [a.step(1.0) for _ in range(10)] == [b.step(1.0) for _ in range(10)]


def test_vehicle_moves_about_speed_times_time():
    vehicle = SimVehicle("V001", ROUTES[0], random.Random(3))
    before = vehicle.position()
    after = vehicle.advance(10.0, time_scale=1.0)
    moved = haversine_m(before["latitude"], before["longitude"], after["latitude"], after["longitude"])
    expected = vehicle.speed_kmh / 3.6 * 10.0
    assert moved == pytest.approx(expected, rel=0.15)


def test_vehicle_laps_the_circuit_without_leaving_it():
    vehicle = SimVehicle("V001", ROUTES[1], random.Random(4))
    for _ in range(2000):
        vehicle.advance(5.0, time_scale=5.0)
    assert 0 <= vehicle.distance_m < vehicle.length_m
    assert vehicle.trip_distance_m > vehicle.length_m        # dio varias vueltas: el recorrido total no se reinicia


def test_empty_fleet_is_rejected():
    with pytest.raises(ValueError):
        Fleet(0)


# ------------------------------------------------ rutas reales (GeoJSON)
def test_default_routes_are_real_street_routes_from_geojson():
    routes = default_routes()
    assert len(routes) == 4
    for route in routes:
        assert route.closed and route.points[0] == route.points[-1]
        assert len(route.points) > 100                       # cientos de vértices, no 3 puntos en línea recta
        assert len(route.streets) == len(route.points) - 1 == len(route.leg_speeds)
        assert all(route.streets) and len(set(route.streets)) >= 5
        assert route.landmarks


def test_vehicles_report_the_street_they_are_on_and_it_belongs_to_their_route():
    fleet = Fleet(4, seed=3)
    for _ in range(30):
        for vehicle, position in zip(fleet.vehicles, fleet.step(2.0)):
            assert position["street"] in set(vehicle.route.streets)


def test_vehicles_stay_close_to_the_street_geometry():
    fleet = Fleet(2, seed=9)
    for _ in range(40):
        for vehicle, position in zip(fleet.vehicles, fleet.step(1.0)):
            nearest = min(haversine_m(position["latitude"], position["longitude"], lat, lon)
                          for _name, lat, lon in vehicle.route.points)
            assert nearest < 120      # los vértices de OSRM están a menos de ~100 m entre sí


def test_speed_follows_the_street_type():
    """Una avenida rápida y una calle lenta de la misma ruta producen velocidades distintas."""
    route = default_routes()[0]
    known = [s for s in route.leg_speeds if s]
    assert max(known) > 2 * min(known)          # p. ej. ~85 km/h en una vía rápida contra ~15 km/h en una calle lenta


def test_route_from_feature_maps_segments_to_legs():
    feature = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-100.3, 25.6], [-100.29, 25.6], [-100.29, 25.61], [-100.3, 25.6]]},
               "properties": {"name": "Mini", "segments": [{"street": "Calle A", "start": 0, "end": 1, "speed_kmh": 30.0},
                                                            {"street": "Calle B", "start": 1, "end": 3, "speed_kmh": None}]}}
    route = Route.from_feature(feature)
    assert route.closed and route.streets == ("Calle A", "Calle B", "Calle B")
    assert route.leg_speeds == (30.0, None, None)
    vehicle = SimVehicle("V001", route, random.Random(1))
    assert vehicle.length_m == pytest.approx(sum(leg[4] for leg in route.legs()))


@pytest.mark.parametrize("geometry", [{"type": "Point", "coordinates": [0, 0]}, {"type": "LineString", "coordinates": [[0, 0]]}])
def test_route_from_feature_rejects_invalid_geometry(geometry):
    with pytest.raises(ValueError):
        Route.from_feature({"type": "Feature", "geometry": geometry, "properties": {}})


def test_default_routes_fall_back_to_straight_circuits_without_the_geojson(tmp_path):
    assert default_routes(tmp_path / "no-existe.geojson") == ROUTES
    broken = tmp_path / "roto.geojson"
    broken.write_text("{no es json", encoding="utf-8")
    assert default_routes(broken) == ROUTES


# ------------------------------------- 3 carros, rutas REALES y escalabilidad
def distance_to_segment_m(lat, lon, leg):
    """Distancia (m) de un punto a un tramo recto, en una proyección plana local (válida a escala de calles)."""
    import math
    lat1, lon1, lat2, lon2, _length = leg
    k = math.cos(math.radians(lat))
    px, py = (lon - lon1) * k * 111_320, (lat - lat1) * 110_540
    bx, by = (lon2 - lon1) * k * 111_320, (lat2 - lat1) * 110_540
    seg2 = bx * bx + by * by
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, (px * bx + py * by) / seg2))
    return math.hypot(px - t * bx, py - t * by)


def test_three_vehicles_each_drive_a_different_real_route():
    fleet = Fleet(3, seed=11)
    assert [v.route.name for v in fleet.vehicles] == [r.name for r in fleet.routes[:3]]
    assert len({v.route.name for v in fleet.vehicles}) == 3
    for _ in range(20):
        for position in fleet.step(2.0):
            assert position["street"] and position["avg_speed"] >= 0


def test_positions_are_really_on_the_street_geometry_not_just_near_it():
    """Cada posición reportada cae SOBRE un tramo del trazado de OpenStreetMap (a menos de 2 m)."""
    fleet = Fleet(3, seed=21, time_scale=8.0)
    for _ in range(120):
        for vehicle, position in zip(fleet.vehicles, fleet.step(1.5)):
            nearest = min(distance_to_segment_m(position["latitude"], position["longitude"], leg) for leg in vehicle._legs)
            assert nearest < 2.0, f"{position['vehicle_id']} está a {nearest:.1f} m de la calle"


def test_real_routes_have_hundreds_of_vertices_unlike_the_straight_circuits():
    real = sum(len(r.points) for r in default_routes())
    straight = sum(len(r.points) for r in ROUTES)
    assert real > 100 * straight


def test_fleet_scales_to_hundreds_of_vehicles_quickly():
    import time
    fleet = Fleet(500, seed=1)
    assert len({v.vehicle_id for v in fleet.vehicles}) == 500
    started = time.perf_counter()
    for _ in range(10):
        positions = fleet.step(1.0)
    elapsed = time.perf_counter() - started
    assert len(positions) == 500 and elapsed < 2.0       # 5,000 actualizaciones de posición en menos de 2 s
    per_route = {}
    for vehicle in fleet.vehicles:
        per_route[vehicle.route.name] = per_route.get(vehicle.route.name, 0) + 1
    assert max(per_route.values()) - min(per_route.values()) <= 1      # reparto parejo entre las 4 rutas


def test_vehicles_on_the_same_route_start_spread_along_it():
    fleet = Fleet(40, seed=5)
    for route in fleet.routes:
        starts = sorted(v.distance_m / v.length_m for v in fleet.vehicles if v.route is route)
        assert len(starts) == 10 and starts[-1] - starts[0] > 0.6       # abarcan buena parte del circuito
        assert all(b > a for a, b in zip(starts, starts[1:]))           # ninguno empieza encima de otro


def test_batches_split_positions_for_the_service_limit():
    positions = [{"vehicle_id": f"V{i:03d}"} for i in range(250)]
    chunks = list(batches(positions))
    assert [len(c) for c in chunks] == [100, 100, 50] and MAX_BATCH == 100
    assert [p for chunk in chunks for p in chunk] == positions
    assert list(batches([])) == []


# ------------------------------------------------ semáforos, peatones, topes y horarios
def _collect(start_time, steps=600, count=3, **kw):
    fleet = Fleet(count, seed=1, start_time=start_time, weekday=1, **kw)
    events, speeds, last = {}, [], []
    for _ in range(steps):
        last = fleet.step(1.0)
        for p in last:
            events[p["event"]] = events.get(p["event"], 0) + 1
            speeds.append(p["speed"])
    return events, speeds, last


def test_vehicles_stop_for_signals_and_pedestrians():
    events, speeds, _ = _collect("12:00")
    assert min(speeds) == 0.0
    assert events.get("traffic_signals", 0) > 0 and events.get("crossing", 0) > 0


def test_rush_hour_is_slower_than_night():
    _, _, rush = _collect("08:00")
    _, _, night = _collect("03:00")
    assert sum(p["avg_speed"] for p in night) > sum(p["avg_speed"] for p in rush)


def test_signal_phases_follow_the_cycle():
    from traffic import Hazard, signal_state
    h = Hazard("x", "traffic_signals", 0, 0, 0, props={"cycle_s": 80, "green_s": 40, "offset_s": 0})
    assert [signal_state(h, t) for t in (0, 39, 41, 45, 79)] == ["green", "green", "yellow", "red", "red"]
    assert signal_state(h, 10, night=True) == "flash"


def test_schedule_windows_cross_midnight():
    from traffic import Schedule
    s = Schedule()
    assert s.is_night(23 * 3600 + 30 * 60) and s.is_night(2 * 3600) and not s.is_night(12 * 3600)
    assert s.rush(8 * 3600, 1) and not s.rush(8 * 3600, 6)          # hora pico solo entre semana
    assert s.school_active(7 * 3600, 2) and not s.school_active(7 * 3600, 5)


def test_fleet_without_hazards_never_stops_for_signals():
    events, speeds, _ = _collect("12:00", hazards=False)
    assert "traffic_signals" not in events and min(speeds) > 0


def test_signals_file_matches_the_routes():
    from simulator_core import hazards_for_route, load_hazards
    collection = load_hazards()
    assert collection is not None
    kinds = {f["properties"]["kind"] for f in collection["features"]}
    assert {"traffic_signals", "crossing", "pothole", "school"} <= kinds
    for route in default_routes():
        found = hazards_for_route(collection, route)
        assert found and all(0 <= h.along_m <= route.length_m() + 1 for h in found)
