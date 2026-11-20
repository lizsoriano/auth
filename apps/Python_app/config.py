"""Configuración de la app: UNA sola dirección, la del API Gateway.

Las apps ya no piden una IP/puerto por microservicio: hablan solo con el gateway (Nginx -> gateway -> servicios) y cada
servicio es una ruta de la API de esa dirección: /api/login, /api/books, /api/users, /api/authors, /api/pedidos y /api/pagos. Cambiar de computadora
o de instancia es cambiar un solo valor.

Se guarda en un JSON junto al ejecutable (no en el código fuente), para poder cambiarla sin tocar una sola línea de
Python (punto 13/14 del enunciado). Compatibilidad: una configuración vieja con las 6 URLs por Nginx se convierte sola a
la dirección única; las URLs sueltas (un puerto por servicio, p. ej. las pruebas de integración) siguen funcionando.
"""
import json
import re
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.local.json"

# clave -> (nombre para mostrar, ruta en el gateway, puerto local de ese servicio si se usa suelto)
SERVICES = {
    "auth": ("Login", "api/login", 5000),
    "books": ("Books", "api/books", 5001),
    "users": ("Users", "api/users", 5002),
    "authors": ("Authors", "api/authors", 5003),
    "pedidos": ("Pedidos", "api/pedidos", 5004),
    "pagos": ("Pagos", "api/pagos", 5005),
}
KEYS = tuple(SERVICES)
DEFAULT_GATEWAY = "http://localhost:8080"   # el gateway de esta computadora; en la VM basta la IP (cambia al encenderla)
REMOTE_BASE = DEFAULT_GATEWAY               # nombre anterior, por compatibilidad


def normalize_gateway(text):
    """'34.1.2.3', 'localhost:8080/x' o 'https://host/' -> 'scheme://host[:puerto]' (sin ruta)."""
    text = (text or "").strip()
    if not text:
        return DEFAULT_GATEWAY
    if "://" not in text:
        text = "http://" + text
    match = re.match(r"^(https?://[^/\s?#]+)", text)
    return match.group(1) if match else text.rstrip("/")


def gateway_urls(base=DEFAULT_GATEWAY):
    """Las 6 rutas colgando de la dirección única del gateway."""
    base = normalize_gateway(base)
    return {key: f"{base}/{prefix}" for key, (_n, prefix, _p) in SERVICES.items()}


remote_urls = gateway_urls     # nombre anterior


def local_urls(host="http://localhost"):
    """Un puerto por servicio (servicios sueltos, sin gateway): solo para pruebas."""
    return {key: f"{host}:{port}" for key, (_n, _pre, port) in SERVICES.items()}


def _with_gateway(base):
    base = normalize_gateway(base)
    result = {"gateway_url": base}
    result.update({f"{k}_url": v for k, v in gateway_urls(base).items()})
    return result


DEFAULTS = _with_gateway(DEFAULT_GATEWAY)


def _derive_missing(stored):
    """URLs sueltas guardadas antes: lo que falte se deduce de la URL de login (mismo equipo con puertos 5000-5005)."""
    auth = str(stored.get("auth_url", "")).rstrip("/")
    local = re.match(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$", auth)
    if local:
        guess = local_urls(re.match(r"^https?://[^:/]+", auth).group(0))
        return {f"{k}_url": v for k, v in guess.items()} | {"gateway_url": ""}
    return dict(DEFAULTS)


def load():
    raw = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            raw = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            raw = {}
    explicit = {f"{k}_url": raw[f"{k}_url"].strip() for k in KEYS
                if isinstance(raw.get(f"{k}_url"), str) and raw[f"{k}_url"].strip()}
    gateway = raw.get("gateway_url")
    if isinstance(gateway, str) and gateway.strip():
        return _with_gateway(gateway)                    # lo normal: una sola dirección
    auth = explicit.get("auth_url", "").rstrip("/")
    for suffix in ("/api/login", "/auth"):               # config guardada antes (por Nginx): se convierte a la dirección única
        if auth.endswith(suffix):
            return _with_gateway(auth[: -len(suffix)])
    if explicit:                                         # URLs sueltas (un puerto por servicio)
        result = _derive_missing(explicit)
        result.update(explicit)
        return result
    return dict(DEFAULTS)


def save(config):
    """Con 'gateway_url' guarda solo esa dirección; sin ella, las URLs sueltas que traiga (pruebas)."""
    if str(config.get("gateway_url", "")).strip():
        clean = {"gateway_url": normalize_gateway(config["gateway_url"])}
    else:
        clean = {f"{k}_url": str(config[f"{k}_url"]).strip() for k in KEYS if f"{k}_url" in config}
    CONFIG_PATH.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")


def restore_defaults():
    save(DEFAULTS)
    return dict(DEFAULTS)


def use_local():
    save(DEFAULTS)
    return dict(DEFAULTS)
