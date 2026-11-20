import json
import time
import urllib.error
import urllib.request

import pytest
import websocket

from gps_service.store import ValidationError, validate_position

POSITION = {"vehicle_id": "V001", "latitude": 25.6866, "longitude": -100.3161, "speed": 45.5, "heading": 270}


def connect(server, role):
    ws = websocket.create_connection(f"ws://{server}/ws?role={role}", timeout=3)
    return ws


def recv(ws):
    return json.loads(ws.recv())


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def get_json(server, path):
    with urllib.request.urlopen(f"http://{server}{path}", timeout=3) as response:
        return response.status, json.loads(response.read())


def history_count(server):
    try:
        return len(get_json(server, "/vehicles/V001/history")[1]["history"])
    except urllib.error.HTTPError:
        return 0


def last_latitude(server):
    try:
        return get_json(server, "/vehicles/V001/history")[1]["history"][-1]["latitude"]
    except urllib.error.HTTPError:
        return None


# ----------------------------------------------------------- validación
def test_validate_position_normalizes_and_stamps():
    position = validate_position({**POSITION, "latitude": 25.68660049, "heading": 360})
    assert position["latitude"] == 25.6866
    assert position["heading"] == 0
    assert position["timestamp"].endswith("+00:00")


def test_validate_position_defaults_speed_and_heading():
    position = validate_position({"vehicle_id": "V9", "latitude": 1, "longitude": 2})
    assert position["speed"] == 0 and position["heading"] == 0


@pytest.mark.parametrize("bad", [
    "texto", 7, None, [],
    {**POSITION, "vehicle_id": ""},
    {**POSITION, "vehicle_id": "V 001"},
    {**POSITION, "vehicle_id": "<script>"},
    {**POSITION, "vehicle_id": 5},
    {**POSITION, "latitude": 91},
    {**POSITION, "latitude": "25.6"},
    {**POSITION, "latitude": True},
    {**POSITION, "longitude": -181},
    {**POSITION, "longitude": float("nan")},
    {**POSITION, "speed": -1},
    {**POSITION, "speed": 401},
    {**POSITION, "heading": 361},
    {k: v for k, v in POSITION.items() if k != "latitude"},
])
def test_validate_position_rejects_bad_payloads(bad):
    with pytest.raises(ValidationError):
        validate_position(bad)


# ------------------------------------------------------------ HTTP
def test_health_and_index(server):
    status, body = get_json(server, "/health")
    assert status == 200
    assert body == {"status": "ok", "service": "gps", "vehicles": 0, "clients": {"gps": 0, "map": 0}, "tracking": "disabled"}
    with urllib.request.urlopen(f"http://{server}/", timeout=3) as response:
        html = response.read().decode()
    assert response.status == 200 and "Monterrey GPS Tracker" in html
    assert "leaflet" in html.lower() and "/static/styles.css" in html and "/static/map.js" in html   # HTML + CSS + Leaflet
    with urllib.request.urlopen(f"http://{server}/static/map.js", timeout=3) as response:
        script = response.read().decode()
    assert "role=map" in script and "L.map(" in script and "L.geoJSON(" in script
    with urllib.request.urlopen(f"http://{server}/static/styles.css", timeout=3) as response:
        assert response.status == 200 and "text/css" in response.headers["Content-Type"]


def test_history_of_unknown_vehicle_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as info:
        get_json(server, "/vehicles/NOPE/history")
    assert info.value.code == 404


# --------------------------------------------------------- WebSocket
def test_map_receives_empty_snapshot_then_live_updates(server):
    mapa = connect(server, "map")
    assert recv(mapa) == {"type": "snapshot", "vehicles": []}
    gps = connect(server, "gps")
    gps.send(json.dumps(POSITION))
    message = recv(mapa)
    assert message["type"] == "update"
    assert message["vehicle"]["vehicle_id"] == "V001"
    assert message["vehicle"]["latitude"] == 25.6866 and message["vehicle"]["heading"] == 270
    feature = message["feature"]                       # la misma posición como GeoJSON Point: [longitud, latitud]
    assert feature["type"] == "Feature" and feature["geometry"] == {"type": "Point", "coordinates": [-100.3161, 25.6866]}
    assert feature["id"] == "V001" and feature["properties"]["speed"] == 45.5
    gps.close(); mapa.close()


def test_late_map_gets_snapshot_with_state_and_trail(server):
    gps = connect(server, "gps")
    for step in range(3):
        gps.send(json.dumps({**POSITION, "latitude": 25.68 + step / 1000}))
    assert wait_for(lambda: history_count(server) == 3)
    mapa = connect(server, "map")
    snapshot = recv(mapa)
    assert snapshot["type"] == "snapshot"
    (vehicle,) = snapshot["vehicles"]
    assert vehicle["latitude"] == 25.682
    assert vehicle["trail"] == [[25.68, -100.3161], [25.681, -100.3161], [25.682, -100.3161]]
    gps.close(); mapa.close()


def test_history_is_bounded(server):
    gps = connect(server, "gps")
    for step in range(8):
        gps.send(json.dumps({**POSITION, "latitude": 25.0 + step / 100}))
    assert wait_for(lambda: last_latitude(server) == 25.07)
    body = get_json(server, "/vehicles/V001/history")[1]
    assert body["count"] == 5  # history_size=5 en el fixture
    assert [p["latitude"] for p in body["history"]] == [25.03, 25.04, 25.05, 25.06, 25.07]
    gps.close()


def test_batch_of_positions_is_broadcast_as_one_geojson_message(server):
    mapa = connect(server, "map"); recv(mapa)
    gps = connect(server, "gps")
    gps.send(json.dumps([POSITION, {**POSITION, "vehicle_id": "V002"}]))
    message = recv(mapa)
    assert message["type"] == "updates"
    assert [v["vehicle_id"] for v in message["vehicles"]] == ["V001", "V002"]
    assert message["features"]["type"] == "FeatureCollection" and len(message["features"]["features"]) == 2
    mapa.settimeout(0.4)
    with pytest.raises(websocket.WebSocketTimeoutException):
        mapa.recv()                      # un lote = UN mensaje (no uno por vehículo)
    gps.close(); mapa.close()


def test_invalid_payload_gets_error_and_is_not_broadcast(server):
    mapa = connect(server, "map"); recv(mapa)
    gps = connect(server, "gps")
    gps.send("esto no es json")
    assert recv(gps) == {"type": "error", "message": "El mensaje no es JSON válido"}
    gps.send(json.dumps({**POSITION, "latitude": 500}))
    error = recv(gps)
    assert error["type"] == "error" and "latitude" in error["message"]
    gps.send(json.dumps(POSITION))      # el canal sigue vivo tras los errores
    assert recv(mapa)["vehicle"]["vehicle_id"] == "V001"
    gps.close(); mapa.close()


def test_batch_with_one_invalid_item_is_rejected_entirely(server):
    mapa = connect(server, "map"); recv(mapa)
    gps = connect(server, "gps")
    gps.send(json.dumps([POSITION, {**POSITION, "vehicle_id": "V002", "speed": -5}]))
    assert recv(gps)["type"] == "error"
    mapa.settimeout(0.5)
    with pytest.raises(websocket.WebSocketTimeoutException):
        mapa.recv()
    gps.close(); mapa.close()


@pytest.mark.parametrize("query", ["", "?role=admin", "?role="])
def test_invalid_role_is_rejected_and_closed(server, query):
    ws = websocket.create_connection(f"ws://{server}/ws{query}", timeout=3)
    assert recv(ws)["type"] == "error"
    opcode, frame = ws.recv_data_frame()
    assert opcode == websocket.ABNF.OPCODE_CLOSE
    assert int.from_bytes(frame.data[:2], "big") == 1008


def test_map_ping_gets_pong_and_disconnect_is_cleaned_up(server):
    mapa = connect(server, "map"); recv(mapa)
    mapa.send(json.dumps({"type": "ping"}))
    assert recv(mapa) == {"type": "pong"}
    assert get_json(server, "/health")[1]["clients"]["map"] == 1
    mapa.close()
    assert wait_for(lambda: get_json(server, "/health")[1]["clients"]["map"] == 0)


# ------------------------------------------------ rutas reales: campos nuevos
REAL = {**POSITION, "street": "Avenida Constitución", "avg_speed": 38.46, "trip_distance_m": 5120.44, "trip_time_s": 480.0}


def test_validate_position_keeps_street_and_trip_fields():
    position = validate_position(REAL)
    assert position["street"] == "Avenida Constitución"
    assert (position["avg_speed"], position["trip_distance_m"], position["trip_time_s"]) == (38.5, 5120.4, 480.0)
    assert "street" not in validate_position(POSITION)          # son opcionales: el contrato anterior sigue valiendo


def test_validate_position_cleans_the_street_text():
    assert validate_position({**POSITION, "street": "  Av. \x00Fundidora\n "})["street"] == "Av. Fundidora"
    assert "street" not in validate_position({**POSITION, "street": "   "})


@pytest.mark.parametrize("extra", [{"street": 5}, {"street": "x" * 121}, {"avg_speed": -1}, {"avg_speed": 401},
                                   {"trip_distance_m": -5}, {"trip_time_s": "10"}, {"trip_time_s": float("inf")}])
def test_validate_position_rejects_bad_real_route_fields(extra):
    with pytest.raises(ValidationError):
        validate_position({**POSITION, **extra})


# ------------------------------------------------------------------ GeoJSON
def test_geojson_vehicles_is_a_feature_collection_of_points(server):
    gps = connect(server, "gps")
    gps.send(json.dumps([REAL, {**REAL, "vehicle_id": "V002", "street": "Avenida Fundidora"}]))
    assert wait_for(lambda: get_json(server, "/health")[1]["vehicles"] == 2)
    with urllib.request.urlopen(f"http://{server}/geojson/vehicles", timeout=3) as response:
        assert "geo+json" in response.headers["Content-Type"]
        data = json.loads(response.read())
    assert data["type"] == "FeatureCollection" and [f["id"] for f in data["features"]] == ["V001", "V002"]
    first = data["features"][0]
    assert first["geometry"]["coordinates"] == [-100.3161, 25.6866]
    assert first["properties"]["street"] == "Avenida Constitución" and "latitude" not in first["properties"]
    gps.close()


def test_routes_geojson_is_served_with_real_streets(server):
    status, data = get_json(server, "/geojson/routes")
    assert status == 200 and data["type"] == "FeatureCollection" and len(data["features"]) == 4
    for feature in data["features"]:
        assert feature["geometry"]["type"] == "LineString" and len(feature["geometry"]["coordinates"]) > 100
        assert len({s["street"] for s in feature["properties"]["segments"]}) >= 5


def test_routes_geojson_missing_file_is_404(tmp_path):
    from gps_service import create_app
    client = create_app(routes_file=tmp_path / "no-existe.geojson").test_client()
    assert client.get("/geojson/routes").status_code == 404


def test_track_geojson_uses_total_distance_over_total_time(server):
    gps = connect(server, "gps")
    # 1 km a 20 km/h (180 s) y luego 1 km a 60 km/h (60 s): 2 km en 240 s = 30 km/h (no 40: el promedio de velocidades engaña)
    points = [(25.6000, 0, 0), (25.6090, 1000, 180), (25.6180, 2000, 240)]
    for lat, meters, seconds in points:
        gps.send(json.dumps({**REAL, "latitude": lat, "trip_distance_m": meters, "trip_time_s": seconds}))
    assert wait_for(lambda: history_count(server) == 3)
    status, feature = get_json(server, "/vehicles/V001/track.geojson")
    assert status == 200 and feature["geometry"]["type"] == "LineString" and len(feature["geometry"]["coordinates"]) == 3
    assert feature["properties"]["avg_speed_kmh"] == pytest.approx(30.0, abs=0.1)
    assert feature["properties"]["distance_m"] == pytest.approx(2000, rel=0.02)     # 0.018° de latitud ≈ 2 km
    gps.close()


def test_track_geojson_without_trip_fields_falls_back_to_server_timestamps(server):
    gps = connect(server, "gps")
    for lat in (25.60, 25.61):
        gps.send(json.dumps({**POSITION, "latitude": lat}))
        time.sleep(0.05)
    assert wait_for(lambda: history_count(server) == 2)
    feature = get_json(server, "/vehicles/V001/track.geojson")[1]
    assert feature["properties"]["avg_speed_kmh"] > 0 and "marcas del servidor" in feature["properties"]["method"]
    gps.close()


def test_track_of_unknown_vehicle_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as info:
        get_json(server, "/vehicles/NOPE/track.geojson")
    assert info.value.code == 404


# ------------------------------------------- escalabilidad: muchos vehículos
def test_one_hundred_vehicles_in_one_batch_reach_the_map_as_one_message(server):
    mapa = connect(server, "map"); recv(mapa)
    gps = connect(server, "gps")
    batch = [{**REAL, "vehicle_id": f"V{index:03d}", "latitude": 25.6 + index / 10000} for index in range(100)]
    started = time.monotonic()
    for _ in range(5):
        gps.send(json.dumps(batch))
    for _ in range(5):
        assert len(recv(mapa)["vehicles"]) == 100
    assert wait_for(lambda: get_json(server, "/health")[1]["vehicles"] == 100)
    assert time.monotonic() - started < 3.0                          # 500 posiciones en menos de 3 s
    assert len(get_json(server, "/geojson/vehicles")[1]["features"]) == 100
    gps.close(); mapa.close()


def test_batches_larger_than_the_limit_are_rejected(server):
    gps = connect(server, "gps")
    gps.send(json.dumps([{**POSITION, "vehicle_id": f"V{i}"} for i in range(101)]))
    assert recv(gps)["type"] == "error"
    gps.close()


# ----------------------------------------------- calle de un punto (OpenStreetMap)
NOMINATIM_ANSWER = {"display_name": "Avenida Constitución, Centro, Monterrey, Nuevo León, México",
                    "address": {"road": "Avenida Constitución", "suburb": "Centro", "city": "Monterrey", "state": "Nuevo León"}}


def geocoder_client(fetch, **kwargs):
    from gps_service import create_app
    from gps_service.geocode import Geocoder
    clock = {"now": 0.0}
    geocoder = Geocoder(fetch=fetch, clock=lambda: clock["now"], sleep=lambda s: clock.__setitem__("now", clock["now"] + s), **kwargs)
    return create_app(geocoder=geocoder).test_client(), geocoder, clock


def test_reverse_geocode_identifies_the_street_and_caches_the_answer():
    calls = []

    def fetch(url):
        calls.append(url)
        return NOMINATIM_ANSWER

    client, geocoder, _ = geocoder_client(fetch)
    first = client.get("/geocode/reverse?lat=25.6700&lon=-100.3090")
    assert first.status_code == 200
    body = first.get_json()
    assert body["street"] == "Avenida Constitución" and body["suburb"] == "Centro" and body["cached"] is False
    assert "OpenStreetMap" in body["source"]
    second = client.get("/geocode/reverse?lat=25.67001&lon=-100.30899").get_json()   # a ~1 m: misma clave de caché
    assert second["cached"] is True and len(calls) == 1 == geocoder.requests_made
    assert "nominatim.openstreetmap.org/reverse" in calls[0] and "lat=25.670000" in calls[0] and "lon=-100.309000" in calls[0]


def test_reverse_geocode_respects_one_request_per_second():
    client, geocoder, clock = geocoder_client(lambda url: NOMINATIM_ANSWER)
    client.get("/geocode/reverse?lat=25.67&lon=-100.30")
    t0 = clock["now"]
    client.get("/geocode/reverse?lat=25.68&lon=-100.31")      # otro punto: debe esperar el intervalo mínimo
    assert clock["now"] - t0 >= 1.0 - 1e-9 and geocoder.requests_made == 2


@pytest.mark.parametrize("query, code", [("", 400), ("?lat=abc&lon=1", 400), ("?lat=25.6", 400),
                                         ("?lat=40.7&lon=-74.0", 422), ("?lat=25.67&lon=-90", 422), ("?lat=nan&lon=-100.3", 422)])
def test_reverse_geocode_rejects_bad_or_out_of_area_points(query, code):
    calls = []
    client, _, _ = geocoder_client(lambda url: calls.append(url) or NOMINATIM_ANSWER)
    assert client.get(f"/geocode/reverse{query}").status_code == code
    assert calls == []                                          # nunca se molesta a Nominatim con puntos inválidos


def test_reverse_geocode_reports_upstream_failures_as_502():
    from gps_service.geocode import GeocodeError

    def broken(url):
        raise GeocodeError("Nominatim no respondió: timeout")

    client, _, _ = geocoder_client(broken)
    response = client.get("/geocode/reverse?lat=25.67&lon=-100.30")
    assert response.status_code == 502 and "Nominatim" in response.get_json()["error"]
    client2, _, _ = geocoder_client(lambda url: {"error": "Unable to geocode"})
    assert client2.get("/geocode/reverse?lat=25.67&lon=-100.30").status_code == 502


def test_geocoder_cache_is_bounded():
    from gps_service.geocode import Geocoder
    geocoder = Geocoder(fetch=lambda url: NOMINATIM_ANSWER, min_interval=0, cache_size=3)
    for index in range(10):
        geocoder.reverse(25.60 + index / 100, -100.30)
    assert len(geocoder._cache) == 3 and geocoder.requests_made == 10


# ------------------------------------------------ semáforos, cruces, topes, baches y horarios
def test_validate_position_keeps_event_and_clock_fields():
    p = validate_position({"vehicle_id": "V1", "latitude": 25.67, "longitude": -100.31, "event": "traffic_signals",
                           "event_text": "Esperando semáforo en rojo", "sim_time": "08:15:30", "sim_day": 1})
    assert p["event"] == "traffic_signals" and p["event_text"] == "Esperando semáforo en rojo"
    assert p["sim_time"] == "08:15:30" and p["sim_day"] == 1


@pytest.mark.parametrize("extra", [{"event": "ovni"}, {"event_text": 5}, {"event_text": "x" * 121},
                                   {"sim_time": "25:00"}, {"sim_time": "8am"}, {"sim_day": 7}, {"sim_day": "lunes"}])
def test_validate_position_rejects_bad_event_fields(extra):
    with pytest.raises(ValidationError):
        validate_position({"vehicle_id": "V1", "latitude": 25.67, "longitude": -100.31, **extra})


def test_signals_geojson_has_real_signals_and_simulated_potholes(server):
    status, data = get_json(server, "/geojson/signals")
    assert status == 200 and data["type"] == "FeatureCollection"
    kinds = {f["properties"]["kind"] for f in data["features"]}
    assert {"traffic_signals", "crossing", "school", "pothole"} <= kinds
    assert all(f["properties"]["source"] == "simulado" for f in data["features"] if f["properties"]["kind"] == "pothole")
    assert all(f["properties"]["source"] == "OpenStreetMap" for f in data["features"] if f["properties"]["kind"] == "traffic_signals")
    assert data["schedule"]["rush_hours"] and data["schedule"]["school"]["speed_limit_kmh"] == 20


def test_signals_geojson_missing_file_is_404(tmp_path):
    from gps_service import create_app
    client = create_app(signals_file=tmp_path / "no-existe.geojson").test_client()
    assert client.get("/geojson/signals").status_code == 404
