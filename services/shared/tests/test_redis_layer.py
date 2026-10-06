import pytest

from library_common import LockNotAcquired, RedisUnavailable


# ---------------------------------------------------------------- caché (opcional)
def test_cache_roundtrip_cuenta_hit_y_miss(layer, metrics, raw):
    assert layer.cache_get("books:1") is None
    assert metrics.get("cache_misses_total") == 1

    assert layer.cache_set("books:1", {"isbn": "1", "price": 10.5}, 60) is True
    assert raw.ttl("books:1") in range(1, 61)
    assert layer.cache_get("books:1") == {"isbn": "1", "price": 10.5}
    assert metrics.get("cache_hits_total") == 1


def test_cache_distingue_lista_vacia_de_no_cacheado(layer):
    layer.cache_set("books:list:all", [], 60)
    assert layer.cache_get("books:list:all") == []


def test_cache_delete_pattern_solo_borra_las_listas(layer, raw, metrics):
    layer.cache_set("books:list:all", [1], 60)
    layer.cache_set("books:list:category=x", [2], 60)
    layer.cache_set("books:9780000000001", {"a": 1}, 60)
    assert layer.cache_delete_pattern("books:list:*") == 2
    assert raw.exists("books:list:all") == 0
    assert raw.exists("books:9780000000001") == 1
    assert metrics.get("cache_invalidations_total") == 2


def test_cache_con_redis_caido_no_lanza_y_cuenta_errores(layer, metrics, redis_down):
    assert layer.cache_get("books:1") is None
    assert layer.cache_set("books:1", {"a": 1}, 60) is False
    assert layer.cache_delete("books:1") == 0
    assert layer.cache_delete_pattern("books:list:*") == 0
    assert metrics.get("cache_errors_total", op="get") == 1
    assert metrics.get("redis_errors_total", op="cache_get") == 1


def test_cache_valor_corrupto_se_trata_como_miss(layer, raw):
    raw.set("books:bad", "{no es json")
    assert layer.cache_get("books:bad") is None


# ------------------------------------------------ revocación de JWT (crítica)
def test_revocar_jti_con_ttl(layer, raw):
    assert layer.is_revoked("abc") is False
    layer.revoke_jti("abc", 600)
    assert layer.is_revoked("abc") is True
    assert raw.ttl("jwt:revoked:abc") in range(1, 601)


def test_revocar_con_ttl_cero_usa_minimo_de_un_segundo(layer, raw):
    layer.revoke_jti("abc", 0)
    assert raw.ttl("jwt:revoked:abc") >= 1


def test_revocacion_falla_cerrado_si_redis_cae(layer, redis_down):
    with pytest.raises(RedisUnavailable):
        layer.is_revoked("abc")
    with pytest.raises(RedisUnavailable):
        layer.revoke_jti("abc", 60)


# ------------------------------------------------------------------- sesión
def test_sesion_put_get_update_conserva_ttl(layer, raw):
    layer.session_put("sid1", {"user_id": 7, "jti": "j1"}, 1800)
    ttl_antes = raw.ttl("session:sid1")
    assert layer.session_update("sid1", jti="j2") is True
    assert layer.session_get("sid1") == {"user_id": 7, "jti": "j2"}
    assert raw.ttl("session:sid1") <= ttl_antes
    assert raw.ttl("session:sid1") > 0


def test_sesion_touch_renueva_y_delete_borra(layer, raw):
    layer.session_put("sid1", {"user_id": 7}, 5)
    assert layer.session_touch("sid1", 1800) is True
    assert raw.ttl("session:sid1") > 1000
    layer.session_delete("sid1")
    assert layer.session_get("sid1") is None
    assert layer.session_touch("sid1", 1800) is False
    assert layer.session_update("sid1", x=1) is False


def test_sesion_falla_cerrado_si_redis_cae(layer, redis_down):
    with pytest.raises(RedisUnavailable):
        layer.session_get("sid1")
    with pytest.raises(RedisUnavailable):
        layer.session_put("sid1", {}, 60)


# ------------------------------------------------------------ refresh token
def test_refresh_token_solo_sirve_una_vez(layer, raw):
    layer.refresh_put("hash1", {"user_id": 7, "sid": "s"}, 86400)
    assert raw.ttl("refresh:hash1") > 80000
    assert layer.refresh_take("hash1") == {"user_id": 7, "sid": "s"}
    assert layer.refresh_take("hash1") is None  # reuso rechazado


# ------------------------------------------------------------------ candados
def test_candado_exclusivo_y_se_libera(layer, raw):
    with layer.lock("order:5", 10):
        assert raw.exists("lock:order:5") == 1
        with pytest.raises(LockNotAcquired):
            with layer.lock("order:5", 10):
                pass
    assert raw.exists("lock:order:5") == 0
    with layer.lock("order:5", 10):
        pass


def test_candado_no_borra_el_de_otro_si_el_suyo_expiro(layer, raw):
    with layer.lock("order:6", 10):
        raw.set("lock:order:6", "otro-proceso")  # el nuestro "expiró" y otro lo tomó
    assert raw.get("lock:order:6") == "otro-proceso"


def test_candado_cuenta_contencion(layer, metrics):
    with layer.lock("x", 10):
        with pytest.raises(LockNotAcquired):
            with layer.lock("x", 10):
                pass
    assert metrics.get("lock_contention_total") == 1


# ---------------------------------------------------------------- idempotencia
def test_idempotencia_primera_vez_completa_y_repite(layer, raw):
    assert layer.idem_claim("payment:idem", "k1", 3600) is True
    assert layer.idem_claim("payment:idem", "k1", 3600) is False
    assert layer.idem_get("payment:idem", "k1") == {"state": "pending"}
    layer.idem_complete("payment:idem", "k1", {"payment_id": 3}, 3600)
    assert layer.idem_get("payment:idem", "k1") == {"state": "done", "result": {"payment_id": 3}}
    assert raw.ttl("payment:idem:k1") > 0


def test_idempotencia_release_permite_reintentar(layer):
    layer.idem_claim("payment:idem", "k2", 3600)
    layer.idem_release("payment:idem", "k2")
    assert layer.idem_claim("payment:idem", "k2", 3600) is True


# --------------------------------------------------------------------- estado
def test_status(layer, redis_down):
    assert layer.status() == "unavailable"


def test_status_ok(layer):
    assert layer.status() == "ok"
