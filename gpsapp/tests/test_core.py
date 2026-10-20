import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator_core import MAX_SPEED_KMH, MIN_SPEED_KMH, ROUTES, Fleet, SimVehicle, bearing_deg, haversine_m  # noqa: E402

MONTERREY_BOX = (25.60, 25.75, -100.50, -100.20)


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


def test_fleet_positions_have_the_microservice_contract():
    fleet = Fleet(6, seed=1)
    for _ in range(50):
        for position in fleet.step(1.0):
            assert set(position) == {"vehicle_id", "latitude", "longitude", "speed", "heading"}
            lat_min, lat_max, lon_min, lon_max = MONTERREY_BOX
            assert lat_min <= position["latitude"] <= lat_max
            assert lon_min <= position["longitude"] <= lon_max
            assert MIN_SPEED_KMH <= position["speed"] <= MAX_SPEED_KMH
            assert 0 <= position["heading"] < 360


def test_vehicle_ids_are_unique_and_valid_for_the_service():
    ids = [p["vehicle_id"] for p in Fleet(10, seed=2).positions()]
    assert len(set(ids)) == 10 and ids[0] == "V001"


def test_same_seed_gives_same_trip():
    a, b = Fleet(3, seed=7), Fleet(3, seed=7)
    assert [a.step(1.0) for _ in range(10)] == [b.step(1.0) for _ in range(10)]


def test_vehicle_moves_about_speed_times_time():
    import random
    vehicle = SimVehicle("V001", ROUTES[0], random.Random(3))
    before = vehicle.position()
    after = vehicle.advance(10.0, time_scale=1.0)
    moved = haversine_m(before["latitude"], before["longitude"], after["latitude"], after["longitude"])
    expected = vehicle.speed_kmh / 3.6 * 10.0
    assert moved == pytest.approx(expected, rel=0.15)


def test_vehicle_laps_the_circuit_without_leaving_it():
    import random
    vehicle = SimVehicle("V001", ROUTES[1], random.Random(4))
    for _ in range(2000):
        vehicle.advance(5.0, time_scale=5.0)
    assert 0 <= vehicle.distance_m < vehicle.length_m


def test_empty_fleet_is_rejected():
    with pytest.raises(ValueError):
        Fleet(0)
