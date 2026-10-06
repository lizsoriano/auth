"""books: JWT (401/403/503), caché Redis de /books y /books/<isbn>, invalidación, Redis caído, CORS, logs."""
import json
import logging
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from app import create_app
from library_common import ConfigError, RedisLayer, SecuritySettings

from conftest import ISSUER, JWT_SECRET, bearer, make_settings, token_for

NEW_BOOK = {"isbn": "9780000000099", "title": "Nuevo libro", "publicationYear": 2024, "price": 150.5,
            "stock": 4, "category": "Tecnico", "format": "Rustica", "authors": "Ada Lovelace"}
ISBN = "9780000000006"


def js(response):
    return json.loads(response.get_data(as_text=True))


# =============================================================== lecturas + caché
def test_lista_se_cachea_y_xml_y_json_comparten_la_misma_entrada(client, db, raw):
    first = client.get("/books?format=json")
    assert first.status_code == 200 and [b["title"] for b in js(first)["books"]] == ["1984", "Cien anos de soledad"]
    assert db.list_calls == 1 and 0 < raw.ttl("books:list:all") <= 60

    again = client.get("/books?format=json")
    xml = client.get("/books")
    assert db.list_calls == 1  # las dos siguientes salieron de Redis
    assert js(again) == js(first)
    assert b"<authors>George Orwell</authors>" in xml.data and b"<stock>20</stock>" in xml.data


def test_las_lecturas_son_publicas(client):
    assert client.get("/books").status_code == 200
    assert client.get(f"/books/{ISBN}").status_code == 200
    assert client.get("/books/images?format=json").status_code == 200
    assert client.get("/wsdl").status_code == 200


def test_libro_por_isbn_se_cachea_aparte_y_reutiliza_la_lista(client, db, raw):
    assert js(client.get(f"/books/{ISBN}?format=json"))["title"] == "1984"
    assert db.list_calls == 1 and raw.exists(f"books:{ISBN}") == 1 and raw.exists("books:list:all") == 1
    assert js(client.get(f"/books/{ISBN}?format=json"))["authors"] == "George Orwell"
    client.get("/books/9780000000001?format=json")  # otro libro: usa la lista ya cacheada, sin ir a la BD
    assert db.list_calls == 1


def test_isbn_inexistente_es_404_y_no_se_cachea(client, db, raw):
    r = client.get("/books/9999999999999?format=json")
    assert r.status_code == 404 and "No existe" in js(r)["error"]
    assert raw.exists("books:9999999999999") == 0


@pytest.mark.parametrize("isbn", ["..%2Fetc", "a" * 40, "x%20y"])
def test_isbn_con_forma_rara_no_crea_claves_en_redis(client, raw, isbn):
    assert client.get(f"/books/{isbn}?format=json").status_code == 404
    assert not [k for k in raw.scan_iter("books:*") if k != "books:list:all"]


def test_parametros_inventados_no_crean_claves_nuevas(client, raw):
    for q in ("x=1", "format=json&y=2", "page=3&sort=title"):
        client.get(f"/books?{q}")
    assert list(raw.scan_iter("books:*")) == ["books:list:all"]


def test_ttl_corto_configurable(db, layer, metrics, raw):
    app = create_app(make_settings(cache_ttl_seconds=5), redis_layer=layer, metrics=metrics)
    app.test_client().get("/books")
    assert 0 < raw.ttl("books:list:all") <= 5


def test_metricas_de_cache(client, metrics):
    client.get("/books")  # books:list:all -> fallo
    client.get("/books")  # books:list:all -> acierto
    client.get(f"/books/{ISBN}")  # books:<isbn> -> fallo, y la lista ya cacheada -> acierto
    assert metrics.get("cache_misses_total") == 2
    assert metrics.get("cache_hits_total") == 2


def test_redis_caido_las_lecturas_siguen_por_postgresql(client, db, metrics, redis_down):
    r = client.get("/books?format=json")
    assert r.status_code == 200 and len(js(r)["books"]) == 2
    assert client.get(f"/books/{ISBN}?format=json").status_code == 200
    assert db.list_calls >= 2  # sin caché cada lectura va a la base
    assert metrics.get("cache_errors_total", op="get") >= 1


# ===================================================================== JWT 401 / 403
@pytest.mark.parametrize("method,path", [("post", "/books"), ("put", f"/books/{ISBN}"),
                                         ("patch", f"/books/{ISBN}"), ("delete", f"/books/{ISBN}")])
class TestEscriturasExigenJwt:
    def test_sin_header_es_401(self, client, db, method, path):
        r = getattr(client, method)(path + "?format=json", json=NEW_BOOK)
        assert r.status_code == 401 and "Authorization" in js(r)["error"]
        assert r.headers["WWW-Authenticate"].startswith("Bearer") and db.write_calls == 0

    def test_formato_incorrecto_es_401(self, client, db, method, path):
        r = getattr(client, method)(path, json=NEW_BOOK, headers={"Authorization": "Token abc"})
        assert r.status_code == 401 and db.write_calls == 0

    def test_token_expirado_es_401(self, client, db, method, path):
        old = datetime.now(timezone.utc) - timedelta(minutes=45)
        r = getattr(client, method)(path, json=NEW_BOOK, headers=bearer(1, now=old))
        assert r.status_code == 401 and db.write_calls == 0

    def test_firma_invalida_es_401(self, client, db, method, path):
        r = getattr(client, method)(path, json=NEW_BOOK, headers=bearer(1, secret="otra-clave-" + "z" * 30))
        assert r.status_code == 401 and db.write_calls == 0

    def test_algoritmo_none_es_401(self, client, db, method, path):
        claims = token_for(1)[1]
        forged = pyjwt.encode(claims, None, algorithm="none")
        r = getattr(client, method)(path, json=NEW_BOOK, headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401 and db.write_calls == 0

    def test_otro_emisor_es_401(self, client, db, method, path):
        r = getattr(client, method)(path, json=NEW_BOOK, headers=bearer(1, issuer="otro"))
        assert r.status_code == 401 and db.write_calls == 0

    def test_claims_incompletos_es_401(self, client, db, method, path):
        claims = token_for(1)[1]
        claims.pop("jti")
        forged = pyjwt.encode(claims, JWT_SECRET, algorithm="HS256")
        r = getattr(client, method)(path, json=NEW_BOOK, headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401 and db.write_calls == 0

    def test_customer_es_403(self, client, db, method, path):
        r = getattr(client, method)(path + "?format=json", json=NEW_BOOK, headers=bearer(3))
        assert r.status_code == 403 and db.write_calls == 0

    def test_token_revocado_es_401(self, client, db, layer, method, path):
        token, claims = token_for(1)
        layer.revoke_jti(claims["jti"], 600)
        r = getattr(client, method)(path, json=NEW_BOOK, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401 and "revocado" in js_or_text(r) and db.write_calls == 0

    def test_redis_caido_deniega_con_503_y_no_toca_la_base(self, client, db, redis_down, method, path):
        r = getattr(client, method)(path + "?format=json", json=NEW_BOOK, headers=bearer(1))
        assert r.status_code == 503 and db.write_calls == 0


def js_or_text(r):
    return r.get_data(as_text=True).lower()


@pytest.mark.parametrize("role_id", [1, 2])
def test_admin_y_staff_pueden_escribir(client, role_id):
    r = client.post("/books?format=json", json=NEW_BOOK, headers=bearer(role_id))
    assert r.status_code == 201 and js(r)["isbn"] == NEW_BOOK["isbn"]


# ================================================================ invalidación
def _caliente(client):
    client.get("/books?format=json")
    client.get(f"/books/{ISBN}?format=json")


def test_post_invalida_la_lista_y_el_libro_nuevo_se_ve(client, db, raw):
    _caliente(client)
    assert client.post("/books?format=json", json=NEW_BOOK, headers=bearer(1)).status_code == 201
    assert raw.exists("books:list:all") == 0
    assert "Nuevo libro" in [b["title"] for b in js(client.get("/books?format=json"))["books"]]


def test_put_invalida_el_libro_y_la_lista(client, raw):
    _caliente(client)
    body = dict(NEW_BOOK, title="1984 (edición nueva)")
    assert client.put(f"/books/{ISBN}?format=json", json=body, headers=bearer(2)).status_code == 200
    assert raw.exists(f"books:{ISBN}") == 0 and raw.exists("books:list:all") == 0
    assert js(client.get(f"/books/{ISBN}?format=json"))["title"] == "1984 (edición nueva)"


def test_patch_invalida_el_libro_y_la_lista(client, raw):
    _caliente(client)
    assert client.patch(f"/books/{ISBN}?format=json", json={"stock": 99}, headers=bearer(1)).status_code == 200
    assert raw.exists(f"books:{ISBN}") == 0 and raw.exists("books:list:all") == 0
    assert js(client.get(f"/books/{ISBN}?format=json"))["stock"] == 99


def test_delete_invalida_y_el_libro_deja_de_existir(client, raw):
    _caliente(client)
    assert client.delete(f"/books/{ISBN}?format=json", headers=bearer(1)).status_code == 200
    assert raw.exists(f"books:{ISBN}") == 0 and raw.exists("books:list:all") == 0
    assert client.get(f"/books/{ISBN}?format=json").status_code == 404
    assert ISBN not in [b["isbn"] for b in js(client.get("/books?format=json"))["books"]]


def test_una_escritura_fallida_no_invalida_la_cache(client, raw):
    _caliente(client)
    assert client.delete("/books/9999999999999?format=json", headers=bearer(1)).status_code == 404
    assert client.post("/books?format=json", json=dict(NEW_BOOK, isbn=ISBN), headers=bearer(1)).status_code == 409
    assert client.post("/books?format=json", json={"isbn": "1"}, headers=bearer(1)).status_code == 400
    assert raw.exists("books:list:all") == 1 and raw.exists(f"books:{ISBN}") == 1


def test_escribir_con_redis_vivo_pero_cache_caida_no_falla(client, layer, monkeypatch):
    """La invalidación es de la caché OPCIONAL: si el barrido falla, la escritura ya hecha no se convierte en error."""
    from redis.exceptions import ConnectionError as RedisConnectionError
    monkeypatch.setattr(layer._r, "scan_iter", lambda **kw: (_ for _ in ()).throw(RedisConnectionError("x")))
    assert client.post("/books?format=json", json=NEW_BOOK, headers=bearer(1)).status_code == 201


# ============================================================== health / metrics
def test_health_reporta_redis_y_sigue_sano_si_redis_cae(client, db):
    assert js(client.get("/health?format=json")) == {"status": "ok", "service": "soap", "database": "connected",
                                                      "redis": "ok"}


def test_health_con_redis_caido_es_200_degradado(client, redis_down):
    r = client.get("/health?format=json")
    assert r.status_code == 200 and js(r)["redis"] == "unavailable"


def test_health_con_postgresql_caido_es_503_aunque_redis_este_bien(client, db):
    db.down = True
    r = client.get("/health?format=json")
    assert r.status_code == 503 and "postgres caído" not in r.get_data(as_text=True)


def test_metrics_exige_jwt_de_administrador(client):
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers=bearer(2)).status_code == 403
    r = client.get("/metrics", headers=bearer(1))
    assert r.status_code == 200 and 'service="books"' in r.get_data(as_text=True)


# ============================================================ arranque, CORS y logs
def test_no_arranca_sin_secreto_jwt_o_sin_redis(layer):
    with pytest.raises(ConfigError, match="JWT_SECRET_KEY"):
        create_app(SecuritySettings(jwt_secret_key="corta"), redis_layer=layer)
    with pytest.raises(ConfigError, match="REDIS_URL"):
        create_app(SecuritySettings(jwt_secret_key=JWT_SECRET))


def test_cors_solo_para_los_origenes_configurados(db, layer):
    app = create_app(make_settings(cors_origins=("https://app.example",)), redis_layer=layer)
    client = app.test_client()
    ok = client.get("/books", headers={"Origin": "https://app.example"})
    other = client.get("/books", headers={"Origin": "https://evil.example"})
    assert ok.headers.get("Access-Control-Allow-Origin") == "https://app.example"
    assert "Access-Control-Allow-Origin" not in other.headers


def test_sin_cors_configurado_no_hay_cabeceras_cors(client):
    assert "Access-Control-Allow-Origin" not in client.get("/books", headers={"Origin": "https://x.example"}).headers


def test_el_token_y_el_header_authorization_nunca_se_registran(client, caplog):
    caplog.set_level(logging.DEBUG)
    good = bearer(1)
    bad = bearer(1, secret="otra-clave-" + "z" * 30)
    client.post("/books", json=NEW_BOOK, headers=good)
    client.post("/books", json=NEW_BOOK, headers=bad)
    client.post("/books", json=NEW_BOOK, headers={"Authorization": "Bearer basura"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert good["Authorization"].split()[1] not in text and bad["Authorization"].split()[1] not in text
    assert "basura" not in text and "Authorization" not in text
