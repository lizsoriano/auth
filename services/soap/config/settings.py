"""Carga de configuración desde .env y setup de logging.

Toda la configuración del servicio vive en variables de entorno (ver
.env.example en la raíz del proyecto) — nunca hardcodeada ni commiteada.
"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    SOAP_HOST = os.getenv("SOAP_HOST", "127.0.0.1")
    SOAP_PORT = int(os.getenv("SOAP_PORT", "5000"))
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    # Solo para scripts/crear_credencial_reportes.py (ver db/connection.py
    # get_admin_connection): soap_service_user es de solo lectura en
    # soap_service_credenciales, así que este script necesita una conexión
    # aparte con privilegios de escritura (p. ej. el mismo superusuario que
    # aplicó sql/soap_module.sql). Nunca la usa el servicio en ejecución.
    ADMIN_DATABASE_URL = os.getenv("ADMIN_DATABASE_URL", "")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    # Ventana de tolerancia (segundos) para wsu:Created y para la
    # deduplicación de wsse:Nonce en WS-Security (ver docs/CONTRATO_DISENO.md §5).
    WSSE_NONCE_WINDOW_SECONDS = int(os.getenv("WSSE_NONCE_WINDOW_SECONDS", "300"))
    # Clave maestra Fernet para cifrar/descifrar password_cifrada en
    # soap_service_credenciales (ver sql/soap_module.sql y soap/security.py).
    # Vive solo aquí (variable de entorno del servidor), nunca en la BD.
    WSSE_MASTER_KEY = os.getenv("WSSE_MASTER_KEY", "")


def configure_logging():
    """Configura logging una sola vez al arrancar la app.

    Regla dura del contrato (§4): el detalle técnico real de cualquier
    error (excepción, SQL, stack trace) va SOLO aquí, nunca en un SOAP
    Fault devuelto al cliente.
    """
    level = getattr(logging, Config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
