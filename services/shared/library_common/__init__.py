"""Piezas comunes de los microservicios Library (login, books, users, authors, pedidos, pagos).

Existe para que los seis servicios hagan EXACTAMENTE lo mismo en lo que debe ser
coherente: validar el JWT, hablar con Redis (mismas claves y tiempos), responder
errores y exponer métricas.
"""
from .cache_keys import book_key, books_list_key, invalidate_all_books, invalidate_books
from .errors import ApiError
from .jwt_auth import (
    ALGORITHM,
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_IDS,
    ROLE_NAMES,
    ROLE_STAFF,
    JwtAuth,
    TokenError,
    decode_access_token,
    issue_access_token,
)
from .metrics import Metrics
from .redis_layer import LockNotAcquired, RedisLayer, RedisUnavailable
from .settings import ConfigError, SecuritySettings, ServiceSettings

__all__ = [
    "book_key", "books_list_key", "invalidate_all_books", "invalidate_books",
    "ALGORITHM", "ApiError", "ConfigError", "JwtAuth", "LockNotAcquired", "Metrics",
    "ROLE_ADMIN", "ROLE_CUSTOMER", "ROLE_IDS", "ROLE_NAMES", "ROLE_STAFF", "RedisLayer",
    "RedisUnavailable", "SecuritySettings", "ServiceSettings", "TokenError", "decode_access_token", "issue_access_token",
]
