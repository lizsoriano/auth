"""Pedidos contra PostgreSQL REAL (migraciones 006-011) y Redis simulado. Se omiten sin TEST_DATABASE_URL."""
import json
import threading

import pytest
from library_common.testing import bearer, token_for


def js(r):
    return json.loads(r.get_data(as_text=True))


def order(client, actor, role, lines, **extra):
    """POST /pedidos con el JWT de `actor` (id de usuario) y `role`; `extra` va en el cuerpo (p. ej. user_id=...)."""
    return client.post("/pedidos?format=json", json={"items": lines, **extra}, headers=bearer(role, actor))


def line(book, quantity=1):
    return {"isbn": book["isbn"], "quantity": quantity}


# ------------------------------------------------------------------ 401 / 503
@pytest.mark.parametrize("method,path", [("post", "/pedidos"), ("get", "/pedidos"), ("get", "/pedidos/1"),
                                         ("patch", "/pedidos/1/status"), ("delete", "/pedidos/1"), ("put", "/pedidos/1")])
def test_todo_exige_jwt(client, method, path):
    r = getattr(client, method)(path + "?format=json", json={})
    assert r.status_code in (401, 405) and (r.status_code == 405 or js(r)["error"]["code"] == "token_missing")


def test_token_revocado_es_401(client, layer):
    token, claims = token_for(3, 5)
    layer.revoke_jti(claims["jti"], 600)
    assert client.get("/pedidos?format=json", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_redis_caido_deniega_503(client, redis_down):
    r = client.get("/pedidos?format=json", headers=bearer(3, 5))
    assert r.status_code == 503 and js(r)["error"]["code"] == "redis_unavailable"


# ------------------------------------------------------------------ crear
def test_crear_pedido_descuenta_stock_suma_lineas_repetidas_y_calcula_el_total(client, world):
    user, book = world.user(), world.book(stock=10, price=100)
    other = world.book(stock=5, price=40)
    r = order(client, user, 3, [line(book, 2), line(book, 1), line(other, 3)])
    body = js(r)["order"]
    assert r.status_code == 201 and body["status"] == "pendiente" and float(body["total"]) == 3 * 100 + 3 * 40
    assert sorted((i["quantity"] for i in body["items"])) == [3, 3] and body["user_id"] == user
    assert world.stock(book["isbn"]) == 7 and world.stock(other["isbn"]) == 2


def test_stock_insuficiente_es_409_y_no_deja_nada_a_medias(client, world):
    user, book, ok = world.user(), world.book(stock=2), world.book(stock=9)
    r = order(client, user, 3, [line(ok, 4), line(book, 3)])
    assert r.status_code == 409 and js(r)["error"]["code"] == "insufficient_stock" and "disponible: 2" in js(r)["error"]["message"]
    assert world.stock(book["isbn"]) == 2 and world.stock(ok["isbn"]) == 9 and world.order_count(user) == 0


def test_isbn_inexistente_404_y_usuario_inactivo_400(client, world):
    user = world.user()
    r = order(client, user, 3, [{"isbn": "0000000000", "quantity": 1}])
    assert r.status_code == 404 and js(r)["error"]["code"] == "book_not_found"
    staff = world.user(role_id=2)
    ghost = world.user(active=False)
    r = order(client, staff, 2, [line(world.book())], user_id=ghost)
    assert r.status_code == 400 and js(r)["error"]["code"] == "invalid_user"


@pytest.mark.parametrize("items", [None, [], "x", [5], [{"isbn": "1"}], [{"quantity": 1}], [{"isbn": "", "quantity": 1}],
                                   [{"isbn": "1", "quantity": 0}], [{"isbn": "1", "quantity": -3}],
                                   [{"isbn": "1", "quantity": "2"}], [{"isbn": "1", "quantity": 1.5}],
                                   [{"isbn": "1", "quantity": True}], [{"isbn": "1", "quantity": 10 ** 7}],
                                   [{"isbn": "9" * 18, "quantity": 1}], [{"isbn": "1", "quantity": 1}] * 101])
def test_validacion_de_lineas_400(client, world, items):
    user = world.user()
    r = client.post("/pedidos?format=json", json={"items": items}, headers=bearer(3, user))
    assert r.status_code == 400 and js(r)["error"]["code"] == "validation_error"


def test_el_cliente_no_crea_pedidos_a_nombre_de_otro(client, world):
    me, other, book = world.user(), world.user(), world.book()
    assert order(client, me, 3, [line(book)], user_id=other).status_code == 403
    assert world.stock(book["isbn"]) == 10
    assert order(client, me, 3, [line(book)], user_id=me).status_code == 201
    staff = world.user(role_id=2)
    r = order(client, staff, 2, [line(book)], user_id=other)
    assert r.status_code == 201 and js(r)["order"]["user_id"] == other


def test_user_id_invalido_400(client, world):
    staff = world.user(role_id=2)
    for bad in ("5", 0, -1, True, 1.5):
        assert order(client, staff, 2, [line(world.book())], user_id=bad).status_code == 400


# ------------------------------------------------------------- listar / ver
def test_cada_cliente_ve_solo_lo_suyo_y_staff_ve_todo(client, world):
    a, b, staff = world.user(), world.user(), world.user(role_id=2)
    book = world.book(stock=20)
    oa = js(order(client, a, 3, [line(book)]))["order"]["order_id"]
    ob = js(order(client, b, 3, [line(book)]))["order"]["order_id"]

    mine = js(client.get("/pedidos?format=json", headers=bearer(3, a)))["orders"]
    assert [o["order_id"] for o in mine] == [oa]
    # un cliente no puede pedir los de otro con ?user_id=
    still_mine = js(client.get(f"/pedidos?format=json&user_id={b}", headers=bearer(3, a)))["orders"]
    assert [o["order_id"] for o in still_mine] == [oa]
    all_ids = [o["order_id"] for o in js(client.get("/pedidos?format=json&limit=200", headers=bearer(2, staff)))["orders"]]
    assert oa in all_ids and ob in all_ids
    only_b = js(client.get(f"/pedidos?format=json&user_id={b}", headers=bearer(2, staff)))["orders"]
    assert [o["order_id"] for o in only_b] == [ob]
    assert js(client.get(f"/pedidos?format=json&user_id={b}&status=pagado", headers=bearer(2, staff)))["orders"] == []


@pytest.mark.parametrize("q", ["status=otro", "limit=0", "limit=abc", "offset=-1", "user_id=x"])
def test_parametros_invalidos_400(client, world, q):
    staff = world.user(role_id=2)
    assert client.get(f"/pedidos?format=json&{q}", headers=bearer(2, staff)).status_code == 400


def test_ver_un_pedido_ajeno_es_404_no_403(client, world):
    a, b, staff = world.user(), world.user(), world.user(role_id=2)
    oid = js(order(client, a, 3, [line(world.book())]))["order"]["order_id"]
    assert client.get(f"/pedidos/{oid}?format=json", headers=bearer(3, a)).status_code == 200
    r = client.get(f"/pedidos/{oid}?format=json", headers=bearer(3, b))
    assert r.status_code == 404 and js(r)["error"]["code"] == "not_found"
    assert client.get(f"/pedidos/{oid}?format=json", headers=bearer(2, staff)).status_code == 200
    assert client.get("/pedidos/99999999?format=json", headers=bearer(2, staff)).status_code == 404


def test_xml_es_el_formato_por_defecto(client, world):
    user = world.user()
    r = client.post("/pedidos", json={"items": [line(world.book())]}, headers=bearer(3, user))
    assert r.status_code == 201 and r.mimetype == "application/xml" and b"<status>pendiente</status>" in r.data


# ----------------------------------------------------------- estados y stock
def test_cancelar_repone_el_stock_y_no_se_puede_repetir(client, world):
    user, other, book = world.user(), world.user(), world.book(stock=10)
    oid = js(order(client, user, 3, [line(book, 4)]))["order"]["order_id"]
    assert world.stock(book["isbn"]) == 6
    assert client.patch(f"/pedidos/{oid}/status?format=json", json={"status": "cancelado"}, headers=bearer(3, other)).status_code == 404
    r = client.patch(f"/pedidos/{oid}/status?format=json", json={"status": "cancelado"}, headers=bearer(3, user))
    assert r.status_code == 200 and js(r)["order"]["status"] == "cancelado" and world.stock(book["isbn"]) == 10
    again = client.delete(f"/pedidos/{oid}?format=json", headers=bearer(3, user))
    assert again.status_code == 409 and js(again)["error"]["code"] == "invalid_transition"
    assert world.stock(book["isbn"]) == 10  # no se repuso dos veces


def test_delete_cancela_el_pedido(client, world):
    user, book = world.user(), world.book(stock=3)
    oid = js(order(client, user, 3, [line(book, 3)]))["order"]["order_id"]
    r = client.delete(f"/pedidos/{oid}?format=json", headers=bearer(3, user))
    assert r.status_code == 200 and js(r)["order"]["status"] == "cancelado" and world.stock(book["isbn"]) == 3


def test_staff_cancela_pedidos_ajenos(client, world):
    user, staff, book = world.user(), world.user(role_id=2), world.book(stock=3)
    oid = js(order(client, user, 3, [line(book, 2)]))["order"]["order_id"]
    assert client.delete(f"/pedidos/{oid}?format=json", headers=bearer(2, staff)).status_code == 200


def test_el_cliente_no_puede_marcar_enviado_y_nadie_marca_pagado_a_mano(client, world):
    user, staff = world.user(), world.user(role_id=2)
    oid = js(order(client, user, 3, [line(world.book())]))["order"]["order_id"]
    url = f"/pedidos/{oid}/status?format=json"
    assert client.patch(url, json={"status": "enviado"}, headers=bearer(3, user)).status_code == 403
    r = client.patch(url, json={"status": "enviado"}, headers=bearer(2, staff))
    assert r.status_code == 409 and js(r)["error"]["code"] == "invalid_transition"  # pendiente no puede pasar a enviado
    r = client.patch(url, json={"status": "pagado"}, headers=bearer(1, staff))
    assert r.status_code == 409 and "Pagos" in js(r)["error"]["message"]
    for bad in ({}, {"status": "x"}, {"status": 3}):
        assert client.patch(url, json=bad, headers=bearer(2, staff)).status_code == 400


def test_pedido_pagado_se_puede_enviar_pero_no_cancelar(client, world):
    from library_common.testing import admin_conn
    user, staff, book = world.user(), world.user(role_id=2), world.book(stock=5)
    oid = js(order(client, user, 3, [line(book)]))["order"]["order_id"]
    with admin_conn() as conn:  # simula lo que hace el servicio Pagos
        conn.execute("UPDATE orders SET status_id = 2 WHERE order_id = %s", (oid,))
    assert client.delete(f"/pedidos/{oid}?format=json", headers=bearer(2, staff)).status_code == 409
    r = client.patch(f"/pedidos/{oid}/status?format=json", json={"status": "enviado"}, headers=bearer(2, staff))
    assert r.status_code == 200 and js(r)["order"]["status"] == "enviado"


# ------------------------------------------------- candado y caché del catálogo
def test_si_otro_proceso_tiene_el_candado_del_pedido_es_409_y_luego_se_puede(client, world, raw):
    user, book = world.user(), world.book()
    oid = js(order(client, user, 3, [line(book)]))["order"]["order_id"]
    raw.set(f"lock:order:{oid}", "otro-servicio", ex=30)  # p. ej. Pagos registrando un pago de este pedido
    r = client.delete(f"/pedidos/{oid}?format=json", headers=bearer(3, user))
    assert r.status_code == 409 and js(r)["error"]["code"] == "order_busy"
    raw.delete(f"lock:order:{oid}")
    assert client.delete(f"/pedidos/{oid}?format=json", headers=bearer(3, user)).status_code == 200
    assert raw.exists(f"lock:order:{oid}") == 0  # el candado se libera siempre


def test_crear_y_cancelar_invalidan_la_cache_del_catalogo(client, world, raw):
    user, book = world.user(), world.book()
    for accion in ("crear", "cancelar"):
        raw.set("books:list:all", "[]", ex=60)
        raw.set(f"books:{book['isbn']}", "{}", ex=60)
        if accion == "crear":
            oid = js(order(client, user, 3, [line(book)]))["order"]["order_id"]
        else:
            client.delete(f"/pedidos/{oid}?format=json", headers=bearer(3, user))
        assert raw.exists("books:list:all") == 0 and raw.exists(f"books:{book['isbn']}") == 0, accion


def test_un_pedido_rechazado_no_invalida_la_cache(client, world, raw):
    user, book = world.user(), world.book(stock=1)
    raw.set("books:list:all", "[]", ex=60)
    assert order(client, user, 3, [line(book, 5)]).status_code == 409
    assert raw.exists("books:list:all") == 1


# ------------------------------------------------------------ concurrencia
def test_dos_clientes_piden_el_ultimo_ejemplar_a_la_vez_solo_uno_lo_consigue(app, world):
    book = world.book(stock=1)
    users = [world.user(), world.user()]
    results, barrier = [], threading.Barrier(2)

    def buy(user):
        client = app.test_client()
        barrier.wait()
        results.append(order(client, user, 3, [line(book)]).status_code)

    threads = [threading.Thread(target=buy, args=(u,)) for u in users]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [201, 409]
    assert world.stock(book["isbn"]) == 0 and sum(world.order_count(u) for u in users) == 1


def test_health_y_metrics(client, world):
    assert js(client.get("/health?format=json")) == {"status": "ok", "service": "pedidos", "database": "connected", "redis": "ok"}
    user = world.user()
    assert client.get("/metrics", headers=bearer(3, user)).status_code == 403
    assert client.get("/metrics", headers=bearer(1, user)).status_code == 200
