"""Conexión a PostgreSQL (library_db) vía psycopg2.

ED-01 (Necesidad -> Decisión -> Justificación, ver README.md):
  Necesidad: el módulo necesita una conexión de BD por petición SOAP.
  Decisión: conexión nueva por request (no pool de conexiones).
  Justificación: el volumen esperado de peticiones de este ejercicio es
  bajo (cliente de escritorio + un par de clientes de interoperabilidad),
  así que un pool añadiría complejidad sin beneficio real. Si el módulo
  creciera a producción real, aquí es donde se cambiaría por
  psycopg2.pool.SimpleConnectionPool sin tocar el resto del código: el
  resto del sistema solo conoce get_connection() como context manager.
"""
import logging
from contextlib import contextmanager

import psycopg2

from config.settings import Config

logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    """Entrega una conexión psycopg2 nueva y la cierra siempre al salir.

    No hace commit/rollback automático: cada función de repository.py es
    responsable de su propia transacción (BEGIN es implícito en psycopg2
    al primer statement; COMMIT/ROLLBACK son explícitos).
    """
    if not Config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL no está configurada. Copie .env.example a .env "
            "y complete la cadena de conexión antes de arrancar el servicio."
        )
    conn = psycopg2.connect(Config.DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_admin_connection():
    """Conexión separada, con más privilegios, SOLO para scripts offline
    de administración (hoy: scripts/crear_credencial_reportes.py).

    soap_service_user (DATABASE_URL, el que usa el servicio en ejecución)
    tiene deliberadamente solo SELECT en soap_service_credenciales (ver
    sql/soap_module.sql) — el proceso HTTP nunca debe poder escribir
    credenciales nuevas, ni siquiera ante un bug. Dar de alta un usuario
    de reportes es una operación administrativa que requiere un rol con
    más privilegios (típicamente el superusuario usado para aplicar
    sql/soap_module.sql), configurado aparte en ADMIN_DATABASE_URL.
    """
    if not Config.ADMIN_DATABASE_URL:
        raise RuntimeError(
            "ADMIN_DATABASE_URL no está configurada en .env. Este script "
            "necesita una conexión con privilegios de escritura sobre "
            "soap_service_credenciales (soap_service_user es de solo "
            "lectura ahí a propósito)."
        )
    conn = psycopg2.connect(Config.ADMIN_DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()
