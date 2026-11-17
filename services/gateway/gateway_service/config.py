"""Tabla de rutas del gateway: prefijo público -> servicio interno (siempre en 127.0.0.1 en la VM)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    name: str          # nombre corto; también el prefijo público: /<name>/...
    default_url: str   # dirección interna por defecto (loopback)
    websocket: bool = False   # si acepta WebSocket en /<name>/ws/...
    description: str = ""

    @property
    def env_var(self):
        return f"{self.name.upper()}_URL"


# Los mismos prefijos y puertos que ya usaban Nginx y las apps (login, books/SOAP, users, authors, pedidos, pagos, rastreo).
SERVICES = (
    Service("auth", "http://127.0.0.1:5000", description="login: JWT, renovación y cierre de sesión"),
    Service("soap", "http://127.0.0.1:5001", description="books y SOAP: catálogo"),
    Service("users", "http://127.0.0.1:5002", description="usuarios, roles y perfil"),
    Service("authors", "http://127.0.0.1:5003", description="autores y sus libros"),
    Service("pedidos", "http://127.0.0.1:5004", description="pedidos, líneas y estados"),
    Service("pagos", "http://127.0.0.1:5005", description="pagos (Idempotency-Key en POST)"),
    Service("gps", "http://127.0.0.1:5900", websocket=True, description="rastreo de pedidos (REST + WebSocket)"),
)


@dataclass(frozen=True)
class Settings:
    upstreams: dict            # nombre -> URL base sin barra final
    connect_timeout: float = 3.0
    read_timeout: float = 30.0
    max_body_bytes: int = 1_048_576

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(
            upstreams={s.name: env.get(s.env_var, s.default_url).strip().rstrip("/") for s in SERVICES},
            connect_timeout=float(env.get("GATEWAY_CONNECT_TIMEOUT", "3")),
            read_timeout=float(env.get("GATEWAY_READ_TIMEOUT", "30")),
            max_body_bytes=int(env.get("GATEWAY_MAX_BODY_BYTES", "1048576")),
        )
