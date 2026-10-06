import pytest
from flask import Flask

from library_common import ConfigError, JwtAuth, Metrics, SecuritySettings
from library_common.observability import register_metrics_endpoint
from library_common import ROLE_ADMIN, ROLE_CUSTOMER, issue_access_token

from conftest import ISSUER, SECRET


def _ok(**override):
    base = dict(jwt_secret_key=SECRET, redis_url="redis://:pw@127.0.0.1:6379/0")
    base.update(override)
    return SecuritySettings(**base)


def test_configuracion_valida():
    _ok().validate()


@pytest.mark.parametrize("cambio", [
    {"jwt_secret_key": ""},
    {"jwt_secret_key": "x" * 31},
    {"redis_url": ""},
    {"redis_url": "http://127.0.0.1:6379"},
    {"jwt_expiration_minutes": 0},
    {"refresh_token_ttl_hours": 0},
    {"redis_socket_timeout": 0},
    {"cache_ttl_seconds": 0},
])
def test_configuracion_invalida(cambio):
    with pytest.raises(ConfigError):
        _ok(**cambio).validate()


def test_from_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    monkeypatch.setenv("REDIS_URL", "redis://:pw@127.0.0.1:6379/0")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "30")
    settings = SecuritySettings.from_env()
    settings.validate()
    assert settings.jwt_expiration_minutes == 20
    assert settings.cors_origins == ("https://a.example", "https://b.example")
    assert settings.cache_ttl_seconds == 30


def test_from_env_entero_invalido(monkeypatch):
    monkeypatch.setenv("CACHE_TTL_SECONDS", "mucho")
    with pytest.raises(ConfigError):
        SecuritySettings.from_env()


def test_prometheus_incluye_servicio_etiquetas_y_ceros():
    metrics = Metrics("books")
    metrics.inc("auth_rejected_total", reason='raro"\n')
    texto = metrics.render_prometheus()
    assert 'cache_hits_total{service="books"} 0' in texto
    assert '# TYPE auth_rejected_total counter' in texto
    assert 'reason="raro\\"\\n"' in texto


def test_endpoint_metrics_exige_admin(layer, metrics):
    auth = JwtAuth(secret_key=SECRET, issuer=ISSUER, redis_layer=layer, metrics=metrics)
    app = Flask(__name__)
    register_metrics_endpoint(app, metrics, auth.required(roles=("admin",)))
    client = app.test_client()
    from datetime import datetime, timezone

    def token(role):
        return issue_access_token(secret_key=SECRET, issuer=ISSUER, user_id=1, role_id=role,
                                  now=datetime.now(timezone.utc), ttl_minutes=20)[0]

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": f"Bearer {token(ROLE_CUSTOMER)}"}).status_code == 403
    r = client.get("/metrics", headers={"Authorization": f"Bearer {token(ROLE_ADMIN)}"})
    assert r.status_code == 200 and b"auth_ok_total" in r.data
