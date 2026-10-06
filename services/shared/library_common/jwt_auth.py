"""JWT HS256 de 20 minutos: emisión (login) y validación (todos los servicios).

Validación estricta en cada servicio, antes de tocar datos:
  1. firma con JWT_SECRET_KEY y algoritmo fijado a HS256 (rechaza alg=none u otro),
  2. expiración (exp), emisor (iss) y claims obligatorios (iat, jti, user_id, role_id),
  3. que el jti NO esté en la lista de revocación de Redis (jwt:revoked:<jti>),
  4. que role_id esté autorizado para la operación (403 si no).

Respuestas: 401 token ausente/inválido/expirado/revocado, 403 rol insuficiente,
503 si Redis no responde (se deniega: nunca se asume "no revocado").
"""
import functools
import logging
import uuid
from datetime import timedelta

import jwt as pyjwt
from flask import g, make_response, request

from .redis_layer import RedisUnavailable
from .serializers import error_payload, render

log = logging.getLogger(__name__)

ALGORITHM = "HS256"

ROLE_ADMIN, ROLE_STAFF, ROLE_CUSTOMER = 1, 2, 3
ROLE_NAMES = {ROLE_ADMIN: "admin", ROLE_STAFF: "staff", ROLE_CUSTOMER: "customer"}
ROLE_IDS = {name: role_id for role_id, name in ROLE_NAMES.items()}

REQUIRED_CLAIMS = ("exp", "iat", "jti", "iss", "user_id", "role_id")


class TokenError(Exception):
    code = "token_invalid"
    status = 401
    message = "El token no es válido."


class TokenMissing(TokenError):
    code = "token_missing"
    message = "Falta la cabecera Authorization. Inicia sesión en /login y envía 'Authorization: Bearer <token>'."


class TokenMalformed(TokenError):
    code = "token_invalid"
    message = "La cabecera Authorization debe tener el formato 'Bearer <token>'."


class TokenExpired(TokenError):
    code = "token_expired"
    message = "El token expiró. Renuévalo con POST /token/refresh o inicia sesión de nuevo."


class TokenRevoked(TokenError):
    code = "token_revoked"
    message = "El token fue revocado (cierre de sesión). Inicia sesión de nuevo."


def issue_access_token(*, secret_key, issuer, user_id, role_id, now, ttl_minutes, jti=None):
    """Crea el JWT de acceso. Devuelve (token, claims) con exp/iat como enteros (epoch)."""
    claims = {
        "iss": issuer,
        "sub": str(user_id),
        "user_id": int(user_id),
        "role_id": int(role_id),
        "role": ROLE_NAMES.get(int(role_id), "unknown"),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "jti": jti or uuid.uuid4().hex,
    }
    return pyjwt.encode(claims, secret_key, algorithm=ALGORITHM), claims


def decode_access_token(token, *, secret_key, issuer, leeway=0):
    """Valida firma, algoritmo, expiración, emisor y claims. Lanza TokenError si algo falla."""
    try:
        claims = pyjwt.decode(
            token,
            secret_key,
            algorithms=[ALGORITHM],  # fijo: un token con alg=none o RS256 se rechaza
            issuer=issuer,
            leeway=leeway,
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except pyjwt.ExpiredSignatureError:
        raise TokenExpired() from None
    except pyjwt.PyJWTError:
        raise TokenError() from None
    if (
        not isinstance(claims.get("user_id"), int) or isinstance(claims.get("user_id"), bool)
        or not isinstance(claims.get("role_id"), int) or isinstance(claims.get("role_id"), bool)
        or not isinstance(claims.get("jti"), str) or not claims["jti"]
    ):
        raise TokenError()
    return claims


def _default_responder(code, message, status):
    return render(error_payload(code, message), status)


def _normalize_roles(roles):
    if not roles:
        return None
    allowed = set()
    for role in roles:
        allowed.add(ROLE_IDS[role] if isinstance(role, str) else int(role))
    return frozenset(allowed)


class JwtAuth:
    """Una instancia por servicio: `auth.required(roles=...)` protege una vista."""

    def __init__(self, *, secret_key, issuer, redis_layer, metrics=None, responder=None, leeway=0):
        if not secret_key or len(secret_key) < 32:
            raise ValueError("JWT_SECRET_KEY debe tener al menos 32 caracteres.")
        self._secret = secret_key
        self._issuer = issuer
        self._redis = redis_layer
        self._metrics = metrics
        self._responder = responder or _default_responder
        self._leeway = leeway

    def _count(self, name, **labels):
        if self._metrics:
            self._metrics.inc(name, **labels)

    def _respond(self, code, message, status):
        response = make_response(self._responder(code, message, status))
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        if status == 401:
            response.headers["WWW-Authenticate"] = 'Bearer realm="library"'
        return response

    def authenticate(self):
        """Devuelve los claims del token de la petición. Lanza TokenError o RedisUnavailable."""
        header = request.headers.get("Authorization")
        if not header:
            raise TokenMissing()
        parts = header.split(" ", 1)
        if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].strip():
            raise TokenMalformed()
        claims = decode_access_token(
            parts[1].strip(), secret_key=self._secret, issuer=self._issuer, leeway=self._leeway)
        if self._redis.is_revoked(claims["jti"]):
            raise TokenRevoked()
        return claims

    def required(self, roles=None):
        allowed = _normalize_roles(roles)

        def decorator(view):
            @functools.wraps(view)
            def wrapper(*args, **kwargs):
                try:
                    claims = self.authenticate()
                except TokenError as exc:
                    self._count("auth_rejected_total", reason=exc.code)
                    # Se registra el motivo, nunca el token ni el header Authorization.
                    log.info("%s %s rechazada: %s", request.method, request.path, exc.code)
                    return self._respond(exc.code, exc.message, exc.status)
                except RedisUnavailable:
                    self._count("auth_rejected_total", reason="redis_unavailable")
                    log.warning("%s %s denegada: Redis no disponible", request.method, request.path)
                    return self._respond(
                        "redis_unavailable",
                        "No se puede verificar la sesión en este momento. Intenta de nuevo en unos segundos.",
                        503,
                    )
                if allowed is not None and claims["role_id"] not in allowed:
                    self._count("auth_rejected_total", reason="forbidden")
                    log.info("%s %s denegada: rol %s sin permiso (user_id=%s)",
                             request.method, request.path, claims["role_id"], claims["user_id"])
                    return self._respond("forbidden", "Tu rol no tiene permiso para esta operación.", 403)
                self._count("auth_ok_total")
                g.jwt_claims = claims
                return view(*args, **kwargs)

            return wrapper

        return decorator
