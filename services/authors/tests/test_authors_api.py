"""Authors contra PostgreSQL REAL (migraciones 006-011) y Redis simulado. Se omiten sin TEST_DATABASE_URL."""
import json

import pytest
from library_common.testing import admin_conn, bearer, token_for


def js(r):
    return json.loads(r.get_data(as_text=True))


ADMIN, STAFF, CUSTOMER = bearer(1), bearer(2), bearer(3)


# --------------------------------------------------------------- lecturas públicas
def test_las_lecturas_son_publicas_y_xml_es_el_formato_por_defecto(client, make_author):
    author_id = make_author()
    assert client.get("/authors").status_code == 200 and client.get("/authors").mimetype == "application/xml"
    r = client.get(f"/authors/{author_id}?format=json")
    assert r.status_code == 200 and js(r)["author"]["author_id"] == author_id and js(r)["author"]["books_count"] == 0
    assert client.get(f"/authors/{author_id}/books?format=json").status_code == 200
    assert client.get("/authors/99999999?format=json").status_code == 404
    assert client.get("/authors/abc").status_code == 404


def test_autor_y_lista_se_cachean_con_ttl_corto_y_se_sirven_desde_redis(client, make_author, raw, metrics):
    author_id = make_author()
    first = js(client.get(f"/authors/{author_id}?format=json"))
    assert 0 < raw.ttl(f"authors:{author_id}") <= 60
    with admin_conn() as conn:  # cambio "por fuera" (p. ej. el monolito): la caché no se entera hasta que expire
        conn.execute("UPDATE authors SET biography = 'cambiada por fuera' WHERE author_id = %s", (author_id,))
    again = js(client.get(f"/authors/{author_id}?format=json"))
    assert again == first and again["author"]["biography"] is None
    assert metrics.get("cache_hits_total") >= 1

    client.get("/authors?format=json&limit=50")
    assert 0 < raw.ttl("authors:list:50") <= 60
    client.get("/authors?format=json&limit=50&offset=10")  # páginas > 1 no se cachean (claves acotadas)
    assert not list(raw.scan_iter("authors:list:50:*")) and len(list(raw.scan_iter("authors:list:*"))) == 1


def test_redis_caido_las_lecturas_siguen_por_postgresql(client, make_author, redis_down):
    author_id = make_author()
    assert client.get(f"/authors/{author_id}?format=json").status_code == 200
    assert client.get("/authors?format=json").status_code == 200


# ------------------------------------------------------------ escrituras: 401 / 403
@pytest.mark.parametrize("method,path", [("post", "/authors"), ("put", "/authors/1"), ("patch", "/authors/1"),
                                         ("delete", "/authors/1"), ("post", "/authors/1/books"),
                                         ("delete", "/authors/1/books/9780000000006")])
def test_las_escrituras_exigen_jwt_y_rol(client, make_author, method, path):
    r = getattr(client, method)(path + "?format=json", json={"first_name": "X"})
    assert r.status_code == 401 and js(r)["error"]["code"] == "token_missing"
    r = getattr(client, method)(path + "?format=json", json={"first_name": "X"}, headers=CUSTOMER)
    assert r.status_code == 403 and js(r)["error"]["code"] == "forbidden"


def test_token_revocado_o_expirado_es_401(client, layer):
    token, claims = token_for(1)
    layer.revoke_jti(claims["jti"], 600)
    assert client.post("/authors?format=json", json={"first_name": "X"}, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_redis_caido_deniega_las_escrituras_con_503(client, redis_down):
    r = client.post("/authors?format=json", json={"first_name": "X"}, headers=ADMIN)
    assert r.status_code == 503 and js(r)["error"]["code"] == "redis_unavailable"


# ------------------------------------------------------------------- CRUD
@pytest.mark.parametrize("headers", [ADMIN, STAFF])
def test_admin_y_staff_hacen_el_ciclo_completo(client, headers):
    r = client.post("/authors?format=json", json={"first_name": "  Isaac ", "last_name": "Asimov", "biography": "Escritor"},
                    headers=headers)
    assert r.status_code == 201
    author = js(r)["author"]
    aid = author["author_id"]
    assert author["first_name"] == "Isaac" and author["books_count"] == 0

    r = client.patch(f"/authors/{aid}?format=json", json={"biography": "Nueva bio"}, headers=headers)
    assert r.status_code == 200 and js(r)["author"]["biography"] == "Nueva bio" and js(r)["author"]["last_name"] == "Asimov"
    r = client.put(f"/authors/{aid}?format=json", json={"first_name": "Isaac Y."}, headers=headers)
    assert r.status_code == 200 and js(r)["author"]["last_name"] is None and js(r)["author"]["biography"] is None

    assert client.delete(f"/authors/{aid}?format=json", headers=headers).status_code == 200
    assert client.get(f"/authors/{aid}?format=json").status_code == 404
    assert client.delete(f"/authors/{aid}?format=json", headers=headers).status_code == 404


@pytest.mark.parametrize("body,campo", [({}, "first_name"), ({"first_name": ""}, "first_name"), ({"first_name": 5}, "first_name"),
                                        ({"first_name": "a" * 121}, "first_name"), ({"first_name": "A", "last_name": 7}, "last_name"),
                                        ({"first_name": "A", "otro": 1}, "otro")])
def test_validacion_de_alta_400(client, body, campo):
    r = client.post("/authors?format=json", json=body, headers=ADMIN)
    assert r.status_code == 400 and campo in json.dumps(js(r)["error"]["details"])


@pytest.mark.parametrize("method,body", [("put", {}), ("patch", {}), ("patch", {"otro": "x"}), ("put", {"last_name": "solo"})])
def test_validacion_de_edicion_400(client, make_author, method, body):
    aid = make_author()
    assert getattr(client, method)(f"/authors/{aid}?format=json", json=body, headers=ADMIN).status_code == 400


def test_editar_un_autor_inexistente_es_404(client):
    assert client.patch("/authors/99999999?format=json", json={"first_name": "X"}, headers=ADMIN).status_code == 404
    assert client.put("/authors/99999999?format=json", json={"first_name": "X"}, headers=ADMIN).status_code == 404


# -------------------------------------------------------- relación con libros
def test_vincular_desvincular_y_borrado_con_libros(client, make_author, make_book):
    aid, book = make_author(), make_book()
    r = client.post(f"/authors/{aid}/books?format=json", json={"isbn": book["isbn"]}, headers=ADMIN)
    assert r.status_code == 201 and js(r)["author"]["books_count"] == 1
    assert [b["isbn"] for b in js(client.get(f"/authors/{aid}/books?format=json"))["books"]] == [book["isbn"]]

    dup = client.post(f"/authors/{aid}/books?format=json", json={"isbn": book["isbn"]}, headers=ADMIN)
    assert dup.status_code == 409 and js(dup)["error"]["code"] == "already_linked"
    gone = client.post(f"/authors/{aid}/books?format=json", json={"isbn": "0000000000"}, headers=ADMIN)
    assert gone.status_code == 404 and js(gone)["error"]["code"] == "book_not_found"
    assert client.post("/authors/99999999/books?format=json", json={"isbn": book["isbn"]}, headers=ADMIN).status_code == 404

    blocked = client.delete(f"/authors/{aid}?format=json", headers=ADMIN)
    assert blocked.status_code == 409 and js(blocked)["error"]["code"] == "reference_conflict"
    assert "constraint" not in blocked.get_data(as_text=True).lower() and "fk_" not in blocked.get_data(as_text=True)

    assert client.delete(f"/authors/{aid}/books/{book['isbn']}?format=json", headers=ADMIN).status_code == 200
    again = client.delete(f"/authors/{aid}/books/{book['isbn']}?format=json", headers=ADMIN)
    assert again.status_code == 404 and js(again)["error"]["code"] == "link_not_found"
    assert client.delete(f"/authors/{aid}?format=json", headers=ADMIN).status_code == 200


@pytest.mark.parametrize("body", [{}, {"isbn": ""}, {"isbn": 5}, {"isbn": "9" * 18}, {"isbn": "1", "author_order": 0},
                                  {"isbn": "1", "author_order": "2"}, {"isbn": "1", "author_order": True}])
def test_validacion_del_vinculo_400(client, make_author, body):
    assert client.post(f"/authors/{make_author()}/books?format=json", json=body, headers=ADMIN).status_code == 400


# ------------------------------------------------------------ invalidación
def test_cada_escritura_invalida_authors_y_el_catalogo_de_libros(client, make_author, make_book, raw):
    aid, book = make_author(), make_book()

    def caliente():
        client.get(f"/authors/{aid}?format=json")
        client.get("/authors?format=json")
        raw.set("books:list:all", "[]", ex=60)  # lo que cachea el servicio books
        raw.set(f"books:{book['isbn']}", "{}", ex=60)

    for hacer in (lambda: client.patch(f"/authors/{aid}?format=json", json={"biography": "x"}, headers=ADMIN),
                  lambda: client.post(f"/authors/{aid}/books?format=json", json={"isbn": book["isbn"]}, headers=STAFF),
                  lambda: client.delete(f"/authors/{aid}/books/{book['isbn']}?format=json", headers=ADMIN)):
        caliente()
        assert raw.exists(f"authors:{aid}") == 1 and raw.exists("books:list:all") == 1
        assert hacer().status_code in (200, 201)  # PATCH y DELETE devuelven 200; vincular devuelve 201
        assert raw.exists(f"authors:{aid}") == 0 and raw.exists("authors:list:50") == 0
        assert raw.exists("books:list:all") == 0 and raw.exists(f"books:{book['isbn']}") == 0


def test_una_escritura_rechazada_no_invalida(client, make_author, raw):
    aid = make_author()
    client.get(f"/authors/{aid}?format=json")
    assert client.patch(f"/authors/{aid}?format=json", json={}, headers=ADMIN).status_code == 400
    assert client.patch(f"/authors/{aid}?format=json", json={"first_name": "X"}, headers=CUSTOMER).status_code == 403
    assert raw.exists(f"authors:{aid}") == 1


def test_health_y_metrics(client):
    assert js(client.get("/health?format=json")) == {"status": "ok", "service": "authors", "database": "connected", "redis": "ok"}
    assert client.get("/metrics", headers=STAFF).status_code == 403
    assert client.get("/metrics", headers=ADMIN).status_code == 200
