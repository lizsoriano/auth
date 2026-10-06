from pathlib import Path

from dotenv import load_dotenv
from library_common import ServiceSettings
from library_common.pg import Pg
from library_common.service_kit import create_base_app, register_health

from .repository import ORDER_ERRORS, OrdersRepository
from .routes import register_routes

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

__all__ = ["create_app"]


def create_app(settings=None, repository=None, redis_layer=None, metrics=None):
    """Fábrica. `repository` y `redis_layer` son inyectables para probar sin PostgreSQL o sin Redis."""
    settings = settings or ServiceSettings.from_env(5004)
    settings.validate(needs_database=repository is None, needs_redis=redis_layer is None)
    app, jwt_auth = create_base_app(name="pedidos", import_name=__name__, settings=settings,
                                    redis_layer=redis_layer, metrics=metrics)
    if repository is None:
        repository = OrdersRepository(Pg(settings.database_url, settings.db_connect_timeout, errors=ORDER_ERRORS))
    app.extensions["repository"] = repository
    register_health(app, "pedidos", repository.ping)
    register_routes(app, jwt_auth, repository)
    return app
