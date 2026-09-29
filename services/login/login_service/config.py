import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class ConfigError(RuntimeError):
    """Raised at startup when the environment is not usable."""


def _bool(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        raise ConfigError(f"{name} debe ser un entero (recibido: {raw!r})")


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 5000
    secret_key: str = ""
    database_url: str = ""
    db_connect_timeout: int = 5
    # Duración lógica de la sesión. Pasado este tiempo, /session responde
    # `session_expired` aunque la cookie siga existiendo.
    session_timeout_minutes: int = 30
    # La cookie vive más que la sesión lógica para poder distinguir
    # "sesión caducada" de "nunca inició sesión".
    cookie_lifetime_hours: int = 24
    cookie_name: str = "login_session"
    cookie_secure: bool = False
    cookie_samesite: str = "Lax"
    cors_origins: tuple = field(default_factory=tuple)
    min_password_length: int = 8
    bcrypt_rounds: int = 12  # mismo costo que el monolito (scripts/create-admin.js)
    email_check_deliverability: bool = False
    # --- Confirmación del correo (envío por el Postfix local de la instancia) ---
    email_confirmation_required: bool = True
    email_token_ttl_hours: int = 24
    resend_cooldown_seconds: int = 60
    public_base_url: str = "http://localhost:5000"  # base del enlace que recibe el usuario
    # Formato con el que se abre el enlace del correo: "json" (se ve JSON en el navegador), "xml" o "" (el predeterminado, XML).
    email_link_format: str = "json"
    smtp_host: str = "localhost"  # Postfix (postfix.service) escuchando en loopback
    smtp_port: int = 25
    smtp_starttls: bool = False
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_timeout: int = 10
    mail_from: str = ""
    log_level: str = "INFO"
    debug: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            host=os.getenv("FLASK_HOST", "127.0.0.1"),
            port=_int("FLASK_PORT", 5000),
            secret_key=os.getenv("FLASK_SECRET_KEY", ""),
            database_url=os.getenv("DATABASE_URL", ""),
            db_connect_timeout=_int("DB_CONNECT_TIMEOUT", 5),
            session_timeout_minutes=_int("SESSION_TIMEOUT_MINUTES", 30),
            cookie_lifetime_hours=_int("SESSION_COOKIE_LIFETIME_HOURS", 24),
            cookie_name=os.getenv("SESSION_COOKIE_NAME", "login_session"),
            cookie_secure=_bool("SESSION_COOKIE_SECURE", False),
            cookie_samesite=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
            cors_origins=tuple(
                item.strip() for item in os.getenv("CORS_ORIGINS", "").split(",") if item.strip()
            ),
            min_password_length=_int("MIN_PASSWORD_LENGTH", 8),
            bcrypt_rounds=_int("BCRYPT_ROUNDS", 12),
            email_check_deliverability=_bool("EMAIL_CHECK_DELIVERABILITY", False),
            email_confirmation_required=_bool("EMAIL_CONFIRMATION_REQUIRED", True),
            email_token_ttl_hours=_int("EMAIL_TOKEN_TTL_HOURS", 24),
            resend_cooldown_seconds=_int("RESEND_COOLDOWN_SECONDS", 60),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:5000").strip().rstrip("/"),
            email_link_format=os.getenv("EMAIL_LINK_FORMAT", "json").strip().lower(),
            smtp_host=os.getenv("SMTP_HOST", "localhost").strip(),
            smtp_port=_int("SMTP_PORT", 25),
            smtp_starttls=_bool("SMTP_STARTTLS", False),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_timeout=_int("SMTP_TIMEOUT", 10),
            mail_from=os.getenv("MAIL_FROM", "").strip(),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            debug=_bool("FLASK_DEBUG", False),
        )

    def validate(self, needs_database=True):
        if len(self.secret_key) < 16:
            raise ConfigError(
                "FLASK_SECRET_KEY falta o es demasiado corta (mínimo 16 caracteres). "
                "Genera una con: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if needs_database and not self.database_url:
            raise ConfigError("DATABASE_URL no está configurada (ver .env.example).")
        if self.session_timeout_minutes <= 0:
            raise ConfigError("SESSION_TIMEOUT_MINUTES debe ser mayor que 0.")
        if self.cookie_lifetime_hours * 60 < self.session_timeout_minutes:
            raise ConfigError("SESSION_COOKIE_LIFETIME_HOURS no puede ser menor que la duración de la sesión.")
        if not 4 <= self.bcrypt_rounds <= 15:
            raise ConfigError("BCRYPT_ROUNDS debe estar entre 4 y 15.")
        if self.email_confirmation_required:
            if not self.mail_from or "@" not in self.mail_from:
                raise ConfigError("MAIL_FROM es obligatorio (p. ej. 'Library <no-reply@tu-dominio>') "
                                  "mientras EMAIL_CONFIRMATION_REQUIRED=true.")
            if not self.public_base_url.startswith(("http://", "https://")):
                raise ConfigError("PUBLIC_BASE_URL debe empezar con http:// o https:// (es la base del enlace del correo).")
            if self.email_link_format not in ("", "xml", "json"):
                raise ConfigError("EMAIL_LINK_FORMAT debe ser json, xml o vacío.")
            if self.email_token_ttl_hours <= 0:
                raise ConfigError("EMAIL_TOKEN_TTL_HOURS debe ser mayor que 0.")
        if self.cookie_samesite not in ("Lax", "Strict", "None"):
            raise ConfigError("SESSION_COOKIE_SAMESITE debe ser Lax, Strict o None.")
        if self.cookie_samesite == "None" and not self.cookie_secure:
            raise ConfigError("SameSite=None exige SESSION_COOKIE_SECURE=true.")
