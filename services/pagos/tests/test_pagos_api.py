"""Pagos contra PostgreSQL REAL (migraciones 006-011) y Redis simulado. Se omiten sin TEST_DATABASE_URL."""
import json
import threading

import pytest
from library_common.testing import bearer, token_for


def js(r):
    return json.loads(r.get_data(as_text=True))


def pay(client, actor, role, order_id, amount, *, key="k-" + "1", method="tarjeta", headers=None, **extra):
    h = {**bearer(role, actor), **({"Idempotency-Key": key} if key else {}), **(headers or {})}
    return client.post("/pagos?format=json", json={"order_id": order_id, "method": method, "amount": amount, **extra}, headers=h)


@pytest.fixture
def setup(world):
    """Cliente, staff, un libro de 250 y un pedido pendiente del cliente (total 250)."""
    user, staff = world.user(), world.user(role_id=2)
    book = world.book(stock=20, price=250)
    order_id, total = world.order_for(user, book)
    return {"user": user, "staff": staff, "book": book, "order": order_id, "total": total}


# ---------------------------------------------------------------- 401 / 405 / 503
@pytest.mark.parametrize("method,path", [("post", "/pagos"), ("get", "/pagos"), ("get", "/pagos/1"),
                                         ("put", "/pagos/1"), ("patch", "/pagos/1"), ("delete", "/pagos/1")])
def test_todo_exige_jwt_incluidos_put_patch_delete(client, method, path):
    r = getattr(client, method)(path + "?format=json", json={})
    assert r.status_code == 401 and js(r)["error"]["code"] == "token_missing"


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_los_pagos_son_inmutables_con_jwt_405(client, world, method):
    user = world.user()
    r = getattr(client, method)("/pagos/1?format=json", json={}, headers=bearer(1, user))
    assert r.status_code == 405 and js(r)["error"]["code"] == "payments_are_immutable"


def test_token_revocado_es_401(client, layer):
    token, claims = token_for(3, 5)
    layer.revoke_jti(claims["jti"], 600)
    assert client.get("/pagos?format=json", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_sin_redis_no_se_cobra_503(client, setup, world, redis_down):
    r = pay(client, setup["user"], 3, setup["order"], setup["total"])
    assert r.status_code == 503 and js(r)["error"]["code"] == "redis_unavailable"
    assert world.order_status(setup["order"]) == "pendiente" and world.payment_count(setup["order"]) == 0


# ------------------------------------------------------------------- pagar
def test_el_cliente_paga_su_pedido_y_queda_pagado_en_la_misma_transaccion(client, setup, world, raw):
    r = pay(client, setup["user"], 3, setup["order"], setup["total"], key="pago-0001")
    p = js(r)["payment"]
    assert r.status_code == 201 and p["order_id"] == setup["order"] and p["order_status"] == "pagado"
    assert float(p["amount"]) == 250 and p["method"] == "tarjeta" and p["status"] == "aprobado"
    assert world.order_status(setup["order"]) == "pagado" and world.payment_count(setup["order"]) == 1
    assert 80000 < raw.ttl(f"payment:idem:{setup['user']}:pago-0001") <= 86400  # clave de idempotencia con TTL de 24 h


def test_reintentar_con_la_misma_clave_devuelve_el_pago_original_sin_cobrar_otra_vez(client, setup, world):
    first = pay(client, setup["user"], 3, setup["order"], setup["total"], key="reintento-1")
    again = pay(client, setup["user"], 3, setup["order"], setup["total"], key="reintento-1")
    assert first.status_code == 201 and again.status_code == 200 and again.headers["Idempotent-Replay"] == "true"
    assert js(again)["payment"]["payment_id"] == js(first)["payment"]["payment_id"]
    assert world.payment_count(setup["order"]) == 1


def test_si_redis_perdio_la_clave_la_base_igual_evita_el_doble_cobro(client, setup, world, raw):
    pay(client, setup["user"], 3, setup["order"], setup["total"], key="perdida-1")
    for k in raw.scan_iter("payment:idem:*"):
        raw.delete(k)  # p. ej. Redis se reinició sin persistencia
    again = pay(client, setup["user"], 3, setup["order"], setup["total"], key="perdida-1")
    assert again.status_code == 200 and "ya registrado" in js(again)["message"].lower()
    assert world.payment_count(setup["order"]) == 1


def test_misma_clave_con_otro_monto_o_pedido_es_409_y_no_devuelve_el_pago_de_otro(client, setup, world):
    pay(client, setup["user"], 3, setup["order"], setup["total"], key="clave-x")
    other_order, other_total = world.order_for(setup["user"], setup["book"])
    r = pay(client, setup["user"], 3, other_order, other_total, key="clave-x")
    assert r.status_code == 409 and js(r)["error"]["code"] == "idempotency_key_reused"
    r = pay(client, setup["user"], 3, setup["order"], 1, key="clave-x")
    assert r.status_code == 409 and js(r)["error"]["code"] == "idempotency_key_reused"
    assert world.order_status(other_order) == "pendiente"


def test_dos_usuarios_pueden_usar_la_misma_clave_sin_chocar(client, setup, world):
    other = world.user()
    order2, total2 = world.order_for(other, setup["book"])
    assert pay(client, setup["user"], 3, setup["order"], setup["total"], key="misma").status_code == 201
    assert pay(client, other, 3, order2, total2, key="misma").status_code == 201


def test_falta_o_es_invalida_la_idempotency_key(client, setup, world):
    r = pay(client, setup["user"], 3, setup["order"], setup["total"], key=None)
    assert r.status_code == 400 and js(r)["error"]["code"] == "idempotency_key_required"
    for bad in ("x" * 65, "con espacios", "ñandú", "a/b"):
        assert pay(client, setup["user"], 3, setup["order"], setup["total"], key=bad).status_code == 400
    assert world.payment_count(setup["order"]) == 0


def test_monto_distinto_del_total_es_409_y_el_pedido_sigue_pendiente(client, setup, world, raw):
    r = pay(client, setup["user"], 3, setup["order"], 100, key="monto-mal")
    assert r.status_code == 409 and js(r)["error"]["code"] == "amount_mismatch" and "250" in js(r)["error"]["message"]
    assert world.order_status(setup["order"]) == "pendiente" and world.payment_count(setup["order"]) == 0
    assert raw.exists(f"payment:idem:{setup['user']}:monto-mal") == 0  # el intento fallido libera la clave
    assert pay(client, setup["user"], 3, setup["order"], setup["total"], key="monto-mal").status_code == 201


@pytest.mark.parametrize("amount,ok", [("250.00", True), ("250", True), (250, True), (250.0, True)])
def test_formatos_de_monto_aceptados(client, setup, amount, ok):
    assert pay(client, setup["user"], 3, setup["order"], amount, key="fmt-ok").status_code == 201


@pytest.mark.parametrize("amount", [250.001, "250.001", -5, 0, "abc", "NaN", "Infinity", True, None, [250], {"v": 250}, 10 ** 11])
def test_montos_invalidos_400(client, setup, world, amount):
    r = pay(client, setup["user"], 3, setup["order"], amount, key="monto-raro")
    assert r.status_code == 400 and js(r)["error"]["code"] == "validation_error"
    assert world.payment_count(setup["order"]) == 0


@pytest.mark.parametrize("body", [{"method": "tarjeta", "amount": 250}, {"order_id": "1", "method": "tarjeta", "amount": 250},
                                  {"order_id": 0, "method": "tarjeta", "amount": 250}, {"order_id": 1, "method": "bitcoin", "amount": 250},
                                  {"order_id": 1, "amount": 250}])
def test_cuerpo_invalido_400(client, setup, body):
    r = client.post("/pagos?format=json", json=body, headers={**bearer(3, setup["user"]), "Idempotency-Key": "k-cuerpo"})
    assert r.status_code == 400 and js(r)["error"]["code"] == "validation_error"


def test_pedido_inexistente_ajeno_o_ya_pagado(client, setup, world):
    other = world.user()
    assert pay(client, setup["user"], 3, 99999999, 10, key="k-a").status_code == 404
    r = pay(client, other, 3, setup["order"], setup["total"], key="k-b")
    assert r.status_code == 404 and world.order_status(setup["order"]) == "pendiente"  # lo ajeno no revela que existe
    assert pay(client, setup["user"], 3, setup["order"], setup["total"], key="k-c").status_code == 201
    r = pay(client, setup["user"], 3, setup["order"], setup["total"], key="k-d")
    assert r.status_code == 409 and js(r)["error"]["code"] == "order_not_payable"
    assert world.payment_count(setup["order"]) == 1


def test_staff_puede_pagar_un_pedido_ajeno(client, setup, world):
    r = pay(client, setup["staff"], 2, setup["order"], setup["total"], key="staff-1")
    assert r.status_code == 201 and js(r)["payment"]["user_id"] == setup["staff"]
    assert world.order_status(setup["order"]) == "pagado"


def test_un_pedido_cancelado_no_se_paga(client, setup, world):
    from library_common.testing import admin_conn
    with admin_conn() as conn:
        conn.execute("SELECT fn_pedido_cambiar_estado(%s, 4::smallint, NULL)", (setup["order"],))
    r = pay(client, setup["user"], 3, setup["order"], setup["total"], key="cancelado-1")
    assert r.status_code == 409 and js(r)["error"]["code"] == "order_not_payable"


# --------------------------------------------------- candado y estado "en curso"
def test_candado_del_pedido_ocupado_es_409_y_se_puede_reintentar_con_la_misma_clave(client, setup, world, raw):
    raw.set(f"lock:order:{setup['order']}", "pedidos-service", ex=30)  # el servicio Pedidos está cambiando este pedido
    r = pay(client, setup["user"], 3, setup["order"], setup["total"], key="busy-1")
    assert r.status_code == 409 and js(r)["error"]["code"] == "order_busy"
    assert raw.exists(f"payment:idem:{setup['user']}:busy-1") == 0
    raw.delete(f"lock:order:{setup['order']}")
    assert pay(client, setup["user"], 3, setup["order"], setup["total"], key="busy-1").status_code == 201
    assert raw.exists(f"lock:order:{setup['order']}") == 0


def test_misma_clave_en_curso_es_409_request_in_progress(client, setup, raw):
    raw.set(f"payment:idem:{setup['user']}:curso-1", json.dumps({"state": "pending"}), ex=60)
    r = pay(client, setup["user"], 3, setup["order"], setup["total"], key="curso-1")
    assert r.status_code == 409 and js(r)["error"]["code"] == "request_in_progress"


# ------------------------------------------------------------- listar / ver
def test_cada_cliente_ve_solo_sus_pagos_y_staff_todos(client, setup, world):
    other = world.user()
    order2, total2 = world.order_for(other, setup["book"])
    pay(client, setup["user"], 3, setup["order"], setup["total"], key="l-1")
    pay(client, other, 3, order2, total2, key="l-2")
    mine = js(client.get("/pagos?format=json", headers=bearer(3, setup["user"])))["payments"]
    assert [p["order_id"] for p in mine] == [setup["order"]]
    everything = {p["order_id"] for p in js(client.get("/pagos?format=json&limit=200", headers=bearer(2, setup["staff"])))["payments"]}
    assert {setup["order"], order2} <= everything
    only = js(client.get(f"/pagos?format=json&order_id={order2}", headers=bearer(2, setup["staff"])))["payments"]
    assert [p["order_id"] for p in only] == [order2]
    assert client.get("/pagos?format=json&order_id=x", headers=bearer(2, setup["staff"])).status_code == 400


def test_ver_un_pago_ajeno_es_404(client, setup, world):
    other = world.user()
    pid = js(pay(client, setup["user"], 3, setup["order"], setup["total"], key="v-1"))["payment"]["payment_id"]
    assert client.get(f"/pagos/{pid}?format=json", headers=bearer(3, setup["user"])).status_code == 200
    assert client.get(f"/pagos/{pid}?format=json", headers=bearer(3, other)).status_code == 404
    assert client.get(f"/pagos/{pid}?format=json", headers=bearer(2, setup["staff"])).status_code == 200
    assert client.get("/pagos/99999999?format=json", headers=bearer(2, setup["staff"])).status_code == 404


def test_xml_por_defecto(client, setup):
    r = client.post("/pagos", json={"order_id": setup["order"], "method": "efectivo", "amount": setup["total"]},
                    headers={**bearer(3, setup["user"]), "Idempotency-Key": "xml-1"})
    assert r.status_code == 201 and r.mimetype == "application/xml" and b"<order_status>pagado</order_status>" in r.data


# -------------------------------------------------------------- concurrencia
def test_dos_peticiones_simultaneas_con_la_misma_clave_cobran_una_sola_vez(app, setup, world):
    results, barrier = [], threading.Barrier(2)

    def go():
        c = app.test_client()
        barrier.wait()
        results.append(pay(c, setup["user"], 3, setup["order"], setup["total"], key="carrera-1").status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert 201 in results and set(results) <= {201, 200, 409}
    assert world.payment_count(setup["order"]) == 1 and world.order_status(setup["order"]) == "pagado"


def test_dos_pagos_simultaneos_del_mismo_pedido_con_claves_distintas_cobran_una_sola_vez(app, setup, world):
    results, barrier = [], threading.Barrier(2)

    def go(key):
        c = app.test_client()
        barrier.wait()
        results.append(pay(c, setup["user"], 3, setup["order"], setup["total"], key=key).status_code)

    threads = [threading.Thread(target=go, args=(k,)) for k in ("dist-a", "dist-b")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [201, 409]
    assert world.payment_count(setup["order"]) == 1


def test_health_y_metrics(client, world):
    assert js(client.get("/health?format=json")) == {"status": "ok", "service": "pagos", "database": "connected", "redis": "ok"}
    user = world.user()
    assert client.get("/metrics", headers=bearer(2, user)).status_code == 403
    assert client.get("/metrics", headers=bearer(1, user)).status_code == 200
