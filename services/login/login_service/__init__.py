import logging
from datetime import timedelta

from flask import Flask
from flask_cors import CORS

from .auth import AuthService, utcnow
from .config import ConfigError, Settings
from .mailer import SmtpMailer
from .docs import docs_blueprint, swagger_ui_blueprint
from .routes import api, register_error_handlers

__all__ = ["create_app", "ConfigError", "Settings"]


def create_app(settings=None, repository=None, clock=utcnow, mailer=None):
    """Fábrica de la aplicación.

    `repository`, `clock` y `mailer` son inyectables para probar sin PostgreSQL ni Postfix.
    """
    settings = settings or Settings.from_env()
    settings.validate(needs_database=repository is None)
    if repository is None:
        from .repository import PostgresRepository  # importa psycopg solo cuando hace falta
        repository = PostgresRepository(settings.database_url, settings.db_connect_timeout)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SESSION_COOKIE_NAME=settings.cookie_name,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=settings.cookie_secure,
        SESSION_COOKIE_SAMESITE=settings.cookie_samesite,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=settings.cookie_lifetime_hours),
    )
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app.extensions["repository"] = repository
    app.extensions["auth_service"] = AuthService(repository, settings, clock, mailer or SmtpMailer(settings))

    if settings.cors_origins:
        CORS(app, supports_credentials=True, origins=list(settings.cors_origins))

    app.register_blueprint(api)
    app.register_blueprint(docs_blueprint)
    app.register_blueprint(swagger_ui_blueprint, url_prefix="/docs")
    register_error_handlers(app)
    return app
