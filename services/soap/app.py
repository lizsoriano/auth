"""Punto de entrada del servicio books (SOAP + REST) de la librería.

Expone:
  GET  /wsdl  -> sirve wsdl/library-classifier.wsdl tal cual.
  POST /soap  -> recibe el Envelope SOAP y lo despacha vía soap/service.py.

  REST bilingüe (XML por defecto, JSON con ?format=json; ver rest_api.py):
  GET    /books, /books/<isbn>, /books/images, /concepts   -> públicas (/books y /books/<isbn> con caché Redis)
  POST   /books  ·  PUT/PATCH/DELETE /books/<isbn>         -> JWT HS256 + rol admin o staff
  GET    /health   -> estado (PostgreSQL y Redis)
  GET    /metrics  -> contadores (JWT de administrador)

Arrancar con: python app.py  (usa SOAP_HOST/SOAP_PORT de .env)  o  flask --app app run  (fábrica create_app).
"""
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, Response, request
from flask_cors import CORS
from library_common import JwtAuth, Metrics, RedisLayer, SecuritySettings
from library_common.observability import register_metrics_endpoint

from config.settings import Config, configure_logging
from soap import service
import rest_api

WSDL_PATH = Path(__file__).resolve().parent / "wsdl" / "library-classifier.wsdl"


def create_app(settings=None, redis_layer=None, metrics=None):
    """Fábrica. `redis_layer` es inyectable para probar sin Redis real.

    Falla al arrancar (no en la primera petición) si falta JWT_SECRET_KEY o REDIS_URL: un servicio que no puede
    validar ni revocar JWT no debe quedar en pie aceptando escrituras.
    """
    configure_logging()
    settings = settings or SecuritySettings.from_env()
    settings.validate(needs_redis=redis_layer is None)
    metrics = metrics or Metrics("books")
    if redis_layer is None:
        redis_layer = RedisLayer.from_url(
            settings.redis_url, connect_timeout=settings.redis_connect_timeout,
            socket_timeout=settings.redis_socket_timeout, metrics=metrics)

    app = Flask(__name__)
    app.extensions["books"] = SimpleNamespace(redis=redis_layer, metrics=metrics, cache_ttl=settings.cache_ttl_seconds)

    jwt_auth = JwtAuth(secret_key=settings.jwt_secret_key, issuer=settings.jwt_issuer, redis_layer=redis_layer,
                       metrics=metrics, responder=rest_api.jwt_error_response)
    rest_api.register(app, jwt_auth=jwt_auth)
    register_metrics_endpoint(app, metrics, jwt_auth.required(roles=("admin",)))

    if settings.cors_origins:  # solo los orígenes de las apps cliente; vacío = CORS desactivado
        CORS(app, origins=list(settings.cors_origins), methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
             allow_headers=["Authorization", "Content-Type"])

    @app.get("/wsdl")
    def get_wsdl():
        return Response(WSDL_PATH.read_bytes(), mimetype="text/xml")

    @app.post("/soap")
    def post_soap():
        raw_body = request.get_data()
        response_bytes, status = service.handle_request(raw_body, remote_addr=request.remote_addr)
        return Response(response_bytes, status=status, mimetype="text/xml")

    return app


if __name__ == "__main__":
    create_app().run(
        host=Config.SOAP_HOST,
        port=Config.SOAP_PORT,
        debug=(Config.FLASK_ENV == "development"),
    )
