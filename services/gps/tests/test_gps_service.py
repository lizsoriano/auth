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
    assert body == {"status": "ok", "service": "gps", "vehicles": 0, "clients": {"gps": 0, "map": 0}}
    with urllib.request.urlopen(f"http://{server}/", timeout=3) as response:
        html = response.read().decode()
    assert response.status == 200 and "Monterrey GPS Tracker" in html and "role=map" in html


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


def test_batch_of_positions_is_broadcast_one_by_one(server):
    mapa = connect(server, "map"); recv(mapa)
    gps = connect(server, "gps")
    gps.send(json.dumps([POSITION, {**POSITION, "vehicle_id": "V002"}]))
    ids = [recv(mapa)["vehicle"]["vehicle_id"], recv(mapa)["vehicle"]["vehicle_id"]]
    assert ids == ["V001", "V002"]
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
