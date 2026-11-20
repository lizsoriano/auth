"""Rastreo de pedidos: código, autorización con JWT, simulación por pedido, HTTP y WebSocket."""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
import websocket
from werkzeug.serving import make_server

import gps_service.app as gps_app
from gps_service import create_app
from gps_service.tracking import TrackingError, TrackingManager

ROUTES = Path(__file__).resolve().parent.parent / "gps_service" / "data" / "rutas_monterrey.geojson"
SECRET = "s" * 40
ISSUER = "library-login"
ORDERS = {   # lo que devolvería el servicio pedidos (order_id -> pedido)
    101: {"order_id": 101, "user_id": 7, "status": "pagado", "total": "250.00", "created_at": "2026-11-03T17:31:52.12345+00:00", "items": []},
    102: {"order_id": 102, "user_id": 8, "status": "pagado", "total": "99.00", "created_at": "2026-11-03T18:00:00+00:00", "items": []},
    103: {"order_id": 103, "user_id": 7, "status": "pendiente", "total": "10.00", "created_at": "2026-11-03T18:00:00+00:00", "items": []},
    104: {"order_id": 104, "user_id": 7, "status": "cancelado", "total": "10.00", "created_at": "2026-11-03T18:00:00+00:00", "items": []},
    105: {"order_id": 105, "user_id": 7, "status": "enviado", "total": "10.00", "created_at": "2026-11-03T18:00:00+00:00", "items": []},
}


def make_token(user_id=7, role_id=3, ttl=600, secret=SECRET, issuer=ISSUER, drop=None):
    now = int(time.time())
    claims = {"iss": issuer, "sub": str(user_id), "user_id": user_id, "role_id": role_id,
              "iat": now, "exp": now + ttl, "jti": "abc123"}
    if drop:
        claims.pop(drop)
    return pyjwt.encode(claims, secret, algorithm="HS256")


class FakeOrders:
    """Imita el contrato real de pedidos: un cliente solo ve lo suyo (lo ajeno es 404); staff/admin ven todo."""

    def get_order(self, order_id, token):
        claims = pyjwt.decode(token, SECRET, algorithms=["HS256"], issuer=ISSUER)
        order = ORDERS.get(order_id)
        if order is None or (order["user_id"] != claims["user_id"] and claims["role_id"] not in (1, 2)):
            raise TrackingError(404, "order_not_found", "No existe ese pedido o no es tuyo.")
        return dict(order)


class ManualClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def manager(clock):
    return TrackingManager(routes_path=ROUTES, orders=FakeOrders(), secret_key=SECRET, issuer=ISSUER, phases=(2, 3, 2),
                           time_scale=60, clock=clock, wall_clock=lambda: datetime(2026, 11, 3, tzinfo=timezone.utc))


# ------------------------------------------------------------------- códigos
def test_code_is_derived_from_the_real_order_and_can_be_parsed(manager):
    code = manager.code_for(ORDERS[101])
    assert code == "LIB-MTY-2026-000101"
    assert manager.order_id_from_code(code) == 101


@pytest.mark.parametrize("code", ["", "LIB-MTY-2026-101", "lib-mty-2026-000101", "LIB-MTY-26-000101", "LIB-MTY-2026-000000",
                                  "LIB-MTY-2026-000101 ", "../etc/passwd"])
def test_malformed_codes_are_rejected(manager, code):
    with pytest.raises(TrackingError) as exc:
        manager.order_id_from_code(code)
    assert exc.value.status == 400


# --------------------------------------------------------------- autenticación
@pytest.mark.parametrize("token", [
    None, "", "no-es-un-jwt",
    make_token(ttl=-10),
    make_token(secret="x" * 40),
    make_token(issuer="otro"),
    make_token(drop="jti"),
    make_token(drop="user_id"),
])
def test_invalid_tokens_are_401(manager, token):
    with pytest.raises(TrackingError) as exc:
        manager.open(token, code="LIB-MTY-2026-000101")
    assert exc.value.status == 401


def test_alg_none_token_is_rejected(manager):
    unsigned = pyjwt.encode({"iss": ISSUER, "user_id": 7, "role_id": 3, "iat": 1, "exp": 9999999999, "jti": "x"}, None, algorithm="none")
    with pytest.raises(TrackingError) as exc:
        manager.open(unsigned, code="LIB-MTY-2026-000101")
    assert exc.value.status == 401


# ----------------------------------------------------------------- autorización
def test_owner_can_track_a_paid_order(manager):
    claims, delivery = manager.open(make_token(7), code="LIB-MTY-2026-000101")
    assert claims["user_id"] == 7 and delivery.order_id == 101


def test_shipped_orders_can_be_tracked_too(manager):
    _claims, delivery = manager.open(make_token(7), order_id=105)
    assert delivery.code == "LIB-MTY-2026-000105"


def test_other_customers_order_is_404_and_does_not_reveal_it_exists(manager):
    with pytest.raises(TrackingError) as exc:
        manager.open(make_token(7), code="LIB-MTY-2026-000102")
    assert exc.value.status == 404
    with pytest.raises(TrackingError) as missing:
        manager.open(make_token(7), code="LIB-MTY-2026-000999")
    assert (missing.value.status, missing.value.code) == (exc.value.status, exc.value.code)


def test_staff_and_admin_can_track_any_order(manager):
    for role in (1, 2):
        _claims, delivery = manager.open(make_token(99, role_id=role), code="LIB-MTY-2026-000102")
        assert delivery.user_id == 8


def test_a_code_of_another_year_for_my_order_is_not_valid(manager):
    with pytest.raises(TrackingError) as exc:
        manager.open(make_token(7), code="LIB-MTY-2025-000101")
    assert exc.value.status == 404


def test_unpaid_and_cancelled_orders_have_nothing_to_track(manager):
    with pytest.raises(TrackingError) as pending:
        manager.open(make_token(7), code="LIB-MTY-2026-000103")
    assert (pending.value.status, pending.value.code) == (409, "order_not_paid")
    with pytest.raises(TrackingError) as cancelled:
        manager.open(make_token(7), code="LIB-MTY-2026-000104")
    assert (cancelled.value.status, cancelled.value.code) == (409, "order_cancelled")


def test_order_id_must_be_a_positive_integer(manager):
    for bad in (None, 0, -3, "5", True):
        with pytest.raises(TrackingError) as exc:
            manager.open(make_token(7), order_id=bad)
        assert exc.value.status == 400


# ------------------------------------------------------ una simulación por pedido
def test_each_order_gets_its_own_route_and_the_same_order_always_the_same(manager):
    seen = set()
    for order_id in range(1, 13):
        order = {"order_id": order_id, "user_id": 7, "status": "pagado", "total": "1", "created_at": "2026-01-01T00:00:00+00:00", "items": []}
        delivery = manager._delivery(order, manager.code_for(order))
        seen.add((delivery.route.name, delivery.route.destination_name))
        again = manager._delivery(order, manager.code_for(order))
        assert again is delivery
    assert len(seen) >= 6   # no es «siempre el mismo vehículo y la misma ruta»


def test_delivery_follows_the_states_and_only_arrives_at_the_end_of_the_route(manager, clock):
    _claims, delivery = manager.open(make_token(7), order_id=101)
    start = clock.now
    depot = delivery.route.coords[0]
    seen = []
    progress = []
    for step in range(0, 400):
        clock.now = start + step * 0.5
        state = delivery.state(clock.now)
        if not seen or seen[-1] != state["status"]:
            seen.append(state["status"])
        progress.append(state["progress"])
        if state["status"] in ("confirmado", "preparando", "enviado"):
            assert (state["position"]["latitude"], state["position"]["longitude"]) == (round(depot[0], 6), round(depot[1], 6))
            assert state["position"]["speed"] == 0 and not state["delivered"]
        if state["status"] == "en_ruta":
            assert 0 <= state["progress"] < 1 and state["position"]["speed"] > 0 and not state["delivered"]
            assert state["position"]["street"] != "" or state["progress"] < 0.01
        if state["status"] == "entregado":
            end = delivery.route.coords[-1]
            assert state["progress"] == 1.0 and state["delivered"] and state["eta_sim_s"] == 0
            assert (state["position"]["latitude"], state["position"]["longitude"]) == (round(end[0], 6), round(end[1], 6))
            assert state["position"]["speed"] == 0
    assert seen == ["confirmado", "preparando", "enviado", "en_ruta", "entregado"]
    assert progress == sorted(progress)


def test_timeline_marks_reached_states_and_state_carries_route_for_the_map(manager, clock):
    _claims, delivery = manager.open(make_token(7), order_id=101)
    clock.now += 4   # preparando
    state = delivery.state(clock.now, with_route=True)
    assert [t["reached"] for t in state["timeline"]] == [True, True, False, False, False]
    assert len(state["route"]) >= 2 and state["trail"][-1] == [state["position"]["latitude"], state["position"]["longitude"]]
    assert state["destination"]["name"] and state["origin"]["name"]


# ----------------------------------------------------------------------- HTTP
@pytest.fixture
def client(manager):
    return create_app(tracking=manager).test_client()


def auth(user_id=7, **kw):
    return {"Authorization": f"Bearer {make_token(user_id, **kw)}"}


def test_post_tracking_requires_a_token(client):
    response = client.post("/tracking", json={"order_id": 101})
    assert response.status_code == 401 and response.json["error"]["code"] == "token_missing"
    assert response.headers["Cache-Control"] == "no-store"


def test_post_tracking_returns_code_status_and_route(client):
    response = client.post("/tracking", json={"order_id": 101}, headers=auth())
    assert response.status_code == 200
    tracking = response.json["tracking"]
    assert tracking["code"] == "LIB-MTY-2026-000101" and tracking["status"] == "confirmado" and tracking["route"]


def test_get_tracking_by_code_checks_the_owner(client):
    ok = client.get("/tracking/LIB-MTY-2026-000101", headers=auth(7))
    assert ok.status_code == 200 and "route" not in ok.json["tracking"]
    assert "route" in client.get("/tracking/LIB-MTY-2026-000101?route=1", headers=auth(7)).json["tracking"]
    assert client.get("/tracking/LIB-MTY-2026-000101", headers=auth(8)).status_code == 404
    assert client.get("/tracking/LIB-MTY-2026-000102", headers=auth(7)).status_code == 404
    assert client.get("/tracking/LIB-MTY-2026-000101").status_code == 401
    assert client.get("/tracking/codigo-raro", headers=auth(7)).status_code == 400
    assert client.get("/tracking/LIB-MTY-2026-000103", headers=auth(7)).status_code == 409


def test_tracking_is_disabled_without_configuration():
    response = create_app(tracking=False).test_client().get("/tracking/LIB-MTY-2026-000101")
    assert response.status_code == 503 and response.json["error"]["code"] == "tracking_disabled"


def test_health_reports_tracking_state(client):
    assert client.get("/health").json["tracking"] == "enabled"


# ------------------------------------------------------------------- WebSocket
@pytest.fixture
def live(monkeypatch):
    """Servidor real con fases y tiempo muy cortos para ver una entrega completa en pocos segundos."""
    monkeypatch.setattr(gps_app, "TRACKING_TICK_S", 0.15)
    mgr = TrackingManager(routes_path=ROUTES, orders=FakeOrders(), secret_key=SECRET, issuer=ISSUER,
                          phases=(0.3, 0.3, 0.3), time_scale=500)
    srv = make_server("127.0.0.1", 0, create_app(tracking=mgr), threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"ws://127.0.0.1:{srv.server_port}/ws/tracking"
    srv.shutdown()
    thread.join(timeout=5)


def open_tracking(url, token, code, timeout=5):
    ws = websocket.create_connection(url, timeout=timeout)
    ws.send(json.dumps({"type": "auth", "token": token, "code": code}))
    return ws


def recv(ws):
    return json.loads(ws.recv())


def test_ws_streams_the_delivery_from_confirmation_to_arrival(live):
    ws = open_tracking(live, make_token(7), "LIB-MTY-2026-000101")
    snapshot = recv(ws)
    assert snapshot["type"] == "snapshot" and snapshot["code"] == "LIB-MTY-2026-000101"
    assert snapshot["route"] and snapshot["status"] in ("confirmado", "preparando")
    statuses, positions, last = [snapshot["status"]], set(), snapshot
    deadline = time.time() + 15
    while not last.get("delivered") and time.time() < deadline:
        last = recv(ws)
        assert last["type"] == "update"
        if last["status"] != statuses[-1]:
            statuses.append(last["status"])
        positions.add((last["position"]["latitude"], last["position"]["longitude"]))
    ws.close()
    assert last["delivered"] and last["progress"] == 1.0
    assert statuses[-1] == "entregado" and statuses.index("en_ruta") < statuses.index("entregado")
    assert len(positions) > 3   # el vehículo realmente se mueve


def test_ws_two_orders_get_different_vehicles(live):
    first = recv(open_tracking(live, make_token(7), "LIB-MTY-2026-000101"))
    second = recv(open_tracking(live, make_token(7), "LIB-MTY-2026-000105"))
    assert first["code"] != second["code"]
    assert (first["route_name"], first["destination"]["name"]) != (second["route_name"], second["destination"]["name"])


@pytest.mark.parametrize("token,code,error", [
    (make_token(8), "LIB-MTY-2026-000101", "order_not_found"),        # pedido ajeno
    (make_token(7), "LIB-MTY-2026-000102", "order_not_found"),
    (make_token(7, ttl=-5), "LIB-MTY-2026-000101", "token_expired"),
    (make_token(7, secret="z" * 40), "LIB-MTY-2026-000101", "token_invalid"),
    (make_token(7), "LIB-MTY-2026-000103", "order_not_paid"),
    (make_token(7), "basura", "invalid_code"),
])
def test_ws_rejects_unauthorized_requests_and_closes(live, token, code, error):
    ws = open_tracking(live, token, code)
    message = recv(ws)
    assert message["type"] == "error" and message["code"] == error
    opcode, _frame = ws.recv_data_frame()
    assert opcode == websocket.ABNF.OPCODE_CLOSE
    ws.close()


def test_ws_requires_the_auth_message_first(live):
    ws = websocket.create_connection(live, timeout=5)
    ws.send(json.dumps({"type": "hello"}))
    assert recv(ws)["code"] == "token_missing"
    ws.close()


def test_ws_answers_ping_and_accepts_a_renewed_token(live):
    ws = open_tracking(live, make_token(7), "LIB-MTY-2026-000101")
    recv(ws)
    ws.send(json.dumps({"type": "ping"}))
    ws.send(json.dumps({"type": "refresh", "token": make_token(7)}))
    ws.send(json.dumps({"type": "refresh", "token": make_token(8)}))      # token de otro usuario: se rechaza
    kinds = {}
    deadline = time.time() + 5
    while time.time() < deadline and not {"pong", "token_refreshed", "error"} <= set(kinds):
        message = recv(ws)
        kinds[message["type"]] = message
    ws.close()
    assert kinds["error"]["code"] == "forbidden"


def test_ws_closes_when_the_token_expires(live):
    ws = open_tracking(live, make_token(7, ttl=2), "LIB-MTY-2026-000101", timeout=8)
    deadline = time.time() + 8
    message = {}
    while time.time() < deadline:
        message = recv(ws)
        if message["type"] == "error":
            break
    assert message["code"] == "token_expired"
    ws.close()
