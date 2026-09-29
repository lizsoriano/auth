"""Validación del JWT que emite services/login (POST /login).

Módulo nuevo y aislado -- no toca soap/service.py (el despacho SOAP no
necesita JWT, sigue igual) ni las rutas GET de rest_api.py (siguen
públicas). Solo se usa como decorador en las 4 rutas de escritura de
/books (ver rest_api.py: crear_libro_view, actualizar_libro_view,
parchear_libro_view, eliminar_libro_view).

La importación de `quiere_json`/`_error` de rest_api.py se hace DENTRO de
la función envuelta (no al importar este módulo) a propósito: rest_api.py
importa este módulo para usar el decorador, así que importarlo al revés
aquí arriba crearía un ciclo. Para cuando la vista decorada realmente se
ejecuta (una petición HTTP), rest_api ya terminó de cargarse por completo.
"""
import functools
import logging

import jwt as pyjwt
from flask import request

from config.settings import Config

logger = logging.getLogger(__name__)


def _rechazar(mensaje):
    from rest_api import _error  # ver docstring del módulo: import diferido, no circular
    return _error(mensaje, 401)


def token_required(view_func):
    """Exige 'Authorization: Bearer <jwt>' válido, firmado con JWT_SECRET
    (HS256) y no expirado. Un token ausente, mal formado, con firma
    inválida, con otro algoritmo o expirado se rechaza con 401 -- nunca
    se ejecuta la vista protegida."""

    @functools.wraps(view_func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        logger.info("%s %s -- Authorization recibida: %s", request.method, request.path, auth_header)
        if not auth_header:
            return _rechazar("Falta la cabecera Authorization. Inicia sesión en /login y "
                             "envía 'Authorization: Bearer <token>'.")
        partes = auth_header.split(" ", 1)
        if len(partes) != 2 or partes[0] != "Bearer" or not partes[1].strip():
            return _rechazar("La cabecera Authorization debe tener el formato 'Bearer <token>'.")
        token = partes[1].strip()

        if not Config.JWT_SECRET:
            # Falla cerrado: sin clave configurada, ningún token puede considerarse válido.
            return _rechazar("El servicio no tiene configurado JWT_SECRET; no se puede validar el token.")

        try:
            payload = pyjwt.decode(token, Config.JWT_SECRET, algorithms=["HS256"])
        except pyjwt.ExpiredSignatureError:
            return _rechazar("El token expiró. Inicia sesión de nuevo en /login para obtener uno nuevo.")
        except pyjwt.InvalidSignatureError:
            return _rechazar("La firma del token no es válida.")
        except pyjwt.InvalidAlgorithmError:
            return _rechazar("El token usa un algoritmo distinto de HS256.")
        except pyjwt.PyJWTError:
            return _rechazar("El token no es válido.")

        request.jwt_payload = payload  # por si alguna vista futura necesita sub/role
        return view_func(*args, **kwargs)

    return wrapper
