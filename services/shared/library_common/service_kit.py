"""Armazón común de los microservicios Users, Authors, Pedidos y Pagos.

`create_base_app` entrega una app Flask con: JWT compartido (JwtAuth), Redis, métricas, CORS solo para los orígenes
configurados, validación de ?format=xml|json, Cache-Control: no-store y manejo uniforme de errores (401/403/404/
409/503... sin filtrar detalles internos). Cada servicio solo agrega sus rutas.
"""
import logging

from flask import Flask, g, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .errors import ApiError
from .jwt_auth import ROLE_ADMIN, ROLE_NAMES, ROLE_STAFF, JwtAuth
from .metrics import Metrics
from .observability import register_metrics_endpoint
from .redis_layer import RedisLayer, RedisUnavailable
from .serializers import error_payload, render, requested_format

log = logging.getLogger(__name__)

PRIVILEGED_ROLES = (ROLE_ADMIN, ROLE_STAFF)


def create_base_app(*, name, import_name, settings, redis_layer=None, metrics=None):
    """`settings` es un ServiceSettings. Devuelve (app, jwt_auth). `redis_layer` es inyectable en pruebas."""
    settings.validate(needs_database=False, needs_redis=redis_layer is None)
    sec = settings.security
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    metrics = metrics or Metrics(name)
    if redis_layer is None:
        redis_layer = RedisLayer.from_url(
            sec.redis_url, connect_timeout=sec.redis_connect_timeout,
            socket_timeout=sec.redis_socket_timeout, metrics=metrics)

    app = Flask(import_name)
    app.extensions["redis"] = redis_layer
    app.extensions["metrics"] = metrics
    app.extensions["settings"] = settings
    jwt_auth = JwtAuth(secret_key=sec.jwt_secret_key, issuer=sec.jwt_issuer, redis_layer=redis_layer, metrics=metrics)
    app.extensions["jwt_auth"] = jwt_auth
    register_metrics_endpoint(app, metrics, jwt_auth.required(roles=("admin",)))

    if sec.cors_origins:  # solo las apps cliente; vacío = CORS desactivado
        CORS(app, origins=list(sec.cors_origins), methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
             allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])

    @app.before_request
    def _validate_format():
        requested_format()  # 400 si format no es xml/json

    @app.after_request
    def _no_cache(response):
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return render(error_payload(exc.code, exc.message, exc.details), exc.status)

    @app.errorhandler(RedisUnavailable)
    def _redis_unavailable(exc):
        return render(error_payload(
            "redis_unavailable", "No se puede verificar la sesión en este momento. Intenta de nuevo en unos segundos."), 503)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return render(error_payload(exc.name.lower().replace(" ", "_"), exc.description), exc.code)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        app.logger.exception("Error no controlado")
        return render(error_payload("internal_error", "Error interno del servidor"), 500)

    return app, jwt_auth


def register_health(app, name, check_database):
    """GET /health: PostgreSQL (obligatorio) y Redis (informativo: sin Redis los endpoints protegidos dan 503)."""

    @app.get("/health")
    def health():
        try:
            check_database()
        except ApiError:
            raise ApiError("database_unavailable", "El servicio está activo pero PostgreSQL no está disponible", 503)
        redis_status = app.extensions["redis"].status()
        return render({"status": "ok", "service": name, "database": "connected", "redis": redis_status})


# ----------------------------------------------------------------- ayudas para rutas
def claims():
    return g.jwt_claims


def is_privileged(c=None):
    return (c or g.jwt_claims)["role_id"] in PRIVILEGED_ROLES


def is_admin(c=None):
    return (c or g.jwt_claims)["role_id"] == ROLE_ADMIN


def json_body():
    """Cuerpo JSON: debe ser un objeto."""
    data = request.get_json(silent=True) if request.is_json else None
    if not isinstance(data, dict):
        raise ApiError("invalid_body", "Envía el cuerpo como un objeto JSON (Content-Type: application/json)", 400)
    return data


def page_args(default_limit=50, max_limit=200):
    """?limit=&offset= (enteros acotados). Valores inválidos -> 400."""
    try:
        limit = int(request.args.get("limit", default_limit))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise ApiError("validation_error", "limit y offset deben ser enteros", 400)
    if not 1 <= limit <= max_limit or offset < 0:
        raise ApiError("validation_error", f"limit debe estar entre 1 y {max_limit} y offset no puede ser negativo", 400)
    return limit, offset


def role_payload():
    return [{"role_id": rid, "name": name} for rid, name in sorted(ROLE_NAMES.items())]
