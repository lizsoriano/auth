"""Persistencia local de la sesión.

Punto 3 del enunciado: "recordar localmente a un usuario no significa que
la sesión del servidor continúe siendo válida". Por eso aquí solo se
guarda la cookie de sesión (un identificador opaco que ya emitió el
servidor) y el correo, para no pedir credenciales de nuevo al abrir la
app -- pero SIEMPRE se revalida contra GET /session antes de confiar en
ella (ver api_client.restore_session). Nunca se guarda la contraseña.
"""
import json
from http.cookiejar import LWPCookieJar
from pathlib import Path

SESSION_PATH = Path(__file__).resolve().parent / "session.local.json"
COOKIE_PATH = Path(__file__).resolve().parent / "cookies.local.txt"


def save(email):
    SESSION_PATH.write_text(json.dumps({"email": email}, ensure_ascii=False), encoding="utf-8")


def load_email():
    if not SESSION_PATH.exists():
        return None
    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8")).get("email")
    except (json.JSONDecodeError, OSError):
        return None


def clear():
    SESSION_PATH.unlink(missing_ok=True)
    COOKIE_PATH.unlink(missing_ok=True)


def cookie_jar():
    """LWPCookieJar persistente en disco: requests.Session la usa tal cual
    (jar de http.cookiejar) y sobrevive a cerrar y volver a abrir la app."""
    jar = LWPCookieJar(str(COOKIE_PATH))
    if COOKIE_PATH.exists():
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except OSError:
            pass
    return jar


def save_cookies(jar):
    try:
        jar.save(ignore_discard=True, ignore_expires=True)
    except OSError:
        pass
