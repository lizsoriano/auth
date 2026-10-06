"""Variables de entorno comunes a todos los servicios (JWT, Redis, CORS)."""
import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """Se lanza al arrancar cuando el entorno no es utilizable."""


def _int(name, default):
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        raise ConfigError(f"{name} debe ser un entero (recibido: {raw!r})")


def _float(name, default):
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        raise ConfigError(f"{name} debe ser un número (recibido: {raw!r})")


@dataclass(frozen=True)
class SecuritySettings:
    jwt_secret_key: str = ""
    jwt_issuer: str = "library-login"
    jwt_expiration_minutes: int = 20
    refresh_token_ttl_hours: int = 24
    redis_url: str = ""
    redis_connect_timeout: float = 1.0
    redis_socket_timeout: float = 1.0
    cache_ttl_seconds: int = 60
    cors_origins: tuple = field(default_factory=tuple)

    @classmethod
    def from_env(cls):
        return cls(
            jwt_secret_key=os.getenv("JWT_SECRET_KEY", ""),
            jwt_issuer=os.getenv("JWT_ISSUER", "library-login").strip() or "library-login",
            jwt_expiration_minutes=_int("JWT_EXPIRATION_MINUTES", 20),
            refresh_token_ttl_hours=_int("REFRESH_TOKEN_TTL_HOURS", 24),
            redis_url=os.getenv("REDIS_URL", "").strip(),
            redis_connect_timeout=_float("REDIS_CONNECT_TIMEOUT", 1.0),
            redis_socket_timeout=_float("REDIS_SOCKET_TIMEOUT", 1.0),
            cache_ttl_seconds=_int("CACHE_TTL_SECONDS", 60),
            cors_origins=tuple(
                item.strip() for item in os.getenv("CORS_ORIGINS", "").split(",") if item.strip()
            ),
        )

    def validate(self, needs_redis=True):
        if len(self.jwt_secret_key) < 32:
            raise ConfigError(
                "JWT_SECRET_KEY falta o es demasiado corta (mínimo 32 caracteres para HS256). "
                "Genera una con: python -c \"import secrets; print(secrets.token_hex(32))\" "
                "-- debe ser LA MISMA en todos los servicios, y solo vive en variables de entorno."
            )
        if needs_redis and not self.redis_url.startswith(("redis://", "rediss://")):
            raise ConfigError(
                "REDIS_URL falta o no empieza con redis:// (formato: redis://:password@host:6379/0)."
            )
        if self.jwt_expiration_minutes <= 0:
            raise ConfigError("JWT_EXPIRATION_MINUTES debe ser mayor que 0.")
        if self.refresh_token_ttl_hours * 60 <= self.jwt_expiration_minutes:
            raise ConfigError("REFRESH_TOKEN_TTL_HOURS debe durar más que el access token (JWT_EXPIRATION_MINUTES).")
        if self.redis_connect_timeout <= 0 or self.redis_socket_timeout <= 0:
            raise ConfigError("REDIS_CONNECT_TIMEOUT y REDIS_SOCKET_TIMEOUT deben ser mayores que 0.")
        if self.cache_ttl_seconds <= 0:
            raise ConfigError("CACHE_TTL_SECONDS debe ser mayor que 0.")


@dataclass(frozen=True)
class ServiceSettings:
    """Configuración de un microservicio nuevo (Users, Authors, Pedidos, Pagos): lo propio + lo común (JWT/Redis)."""
    host: str = "127.0.0.1"
    port: int = 5000
    database_url: str = ""
    db_connect_timeout: int = 5
    log_level: str = "INFO"
    bcrypt_rounds: int = 12
    min_password_length: int = 8
    security: SecuritySettings = field(default_factory=SecuritySettings)

    @classmethod
    def from_env(cls, default_port):
        return cls(
            host=os.getenv("FLASK_HOST", "127.0.0.1"),
            port=_int("FLASK_PORT", default_port),
            database_url=os.getenv("DATABASE_URL", ""),
            db_connect_timeout=_int("DB_CONNECT_TIMEOUT", 5),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            bcrypt_rounds=_int("BCRYPT_ROUNDS", 12),
            min_password_length=_int("MIN_PASSWORD_LENGTH", 8),
            security=SecuritySettings.from_env(),
        )

    def validate(self, needs_database=True, needs_redis=True):
        if needs_database and not self.database_url:
            raise ConfigError("DATABASE_URL no está configurada (ver .env.example).")
        if not 4 <= self.bcrypt_rounds <= 15:
            raise ConfigError("BCRYPT_ROUNDS debe estar entre 4 y 15.")
        if self.min_password_length < 8:
            raise ConfigError("MIN_PASSWORD_LENGTH no puede ser menor que 8.")
        self.security.validate(needs_redis=needs_redis)
