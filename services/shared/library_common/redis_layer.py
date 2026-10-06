"""Capa Redis común a todos los servicios.

Dos familias de operaciones con políticas de fallo OPUESTAS a propósito:

* Caché (cache_*): OPCIONAL. Si Redis falla se cuenta, se registra y se devuelve
  "no hay dato" -- el servicio sigue leyendo de PostgreSQL.
* Sesión, refresh token, revocación de JWT, candados e idempotencia: CRÍTICAS.
  Si Redis falla lanzan RedisUnavailable y el llamador debe DENEGAR (503). Nunca
  se asume "no está revocado" ni "la sesión es válida" cuando Redis no responde.

Claves (todas con TTL): jwt:revoked:<jti>, session:<sid>, refresh:<sha256>,
lock:<nombre>, <namespace>:<clave> (idempotencia), books:*, authors:* (caché).
"""
import json
import logging
import secrets
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import redis
from redis.exceptions import RedisError

log = logging.getLogger(__name__)

KEY_REVOKED = "jwt:revoked:"
KEY_SESSION = "session:"
KEY_REFRESH = "refresh:"
KEY_LOCK = "lock:"


class RedisUnavailable(Exception):
    """Redis no respondió (conexión, timeout, autenticación). Las operaciones críticas deben denegar."""


class LockNotAcquired(Exception):
    """Otro proceso tiene el candado."""


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


class RedisLayer:
    def __init__(self, client, metrics=None):
        self._r = client
        self.metrics = metrics

    @classmethod
    def from_url(cls, url, *, connect_timeout=1.0, socket_timeout=1.0, metrics=None, max_connections=20):
        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
            health_check_interval=30,
            max_connections=max_connections,
            decode_responses=True,
        )
        return cls(client, metrics)

    # ------------------------------------------------------------------ interno
    def _count(self, name, **labels):
        if self.metrics:
            self.metrics.inc(name, **labels)

    def _call(self, op, fn, *, retries=0):
        """Ejecuta fn(); `retries` solo debe ser > 0 en lecturas idempotentes."""
        attempt = 0
        while True:
            try:
                return fn()
            except RedisError as exc:
                attempt += 1
                if attempt > retries:
                    self._count("redis_errors_total", op=op)
                    # Solo el nombre de la excepción: nunca el mensaje ni la URL (puede incluir la contraseña).
                    log.warning("Redis no disponible en %s (%s)", op, type(exc).__name__)
                    raise RedisUnavailable(op) from exc

    # ------------------------------------------------------------------- estado
    def ping(self):
        try:
            return bool(self._call("ping", self._r.ping))
        except RedisUnavailable:
            return False

    def status(self):
        return "ok" if self.ping() else "unavailable"

    # ------------------------------------------------------------ caché (opcional)
    def cache_get(self, key):
        """Devuelve el valor guardado o None (no existe, o Redis no responde)."""
        try:
            raw = self._call("cache_get", lambda: self._r.get(key), retries=1)
        except RedisUnavailable:
            self._count("cache_errors_total", op="get")
            return None
        if raw is None:
            self._count("cache_misses_total")
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            self._count("cache_misses_total")
            return None
        self._count("cache_hits_total")
        return value

    def cache_set(self, key, value, ttl_seconds):
        try:
            payload = json.dumps(value, default=_json_default, ensure_ascii=False)
            self._call("cache_set", lambda: self._r.set(key, payload, ex=max(int(ttl_seconds), 1)))
            return True
        except RedisUnavailable:
            self._count("cache_errors_total", op="set")
            return False

    def cache_delete(self, *keys):
        if not keys:
            return 0
        try:
            removed = self._call("cache_delete", lambda: self._r.unlink(*keys))
        except RedisUnavailable:
            self._count("cache_errors_total", op="delete")
            return 0
        if self.metrics and removed:
            self.metrics.inc("cache_invalidations_total", removed)
        return removed

    def cache_delete_pattern(self, pattern):
        """Borra todas las claves que coinciden (SCAN + UNLINK en lotes; nunca KEYS)."""
        removed = 0
        try:
            batch = []
            for key in self._r.scan_iter(match=pattern, count=200):
                batch.append(key)
                if len(batch) >= 200:
                    removed += self._call("cache_delete_pattern", lambda b=tuple(batch): self._r.unlink(*b))
                    batch = []
            if batch:
                removed += self._call("cache_delete_pattern", lambda b=tuple(batch): self._r.unlink(*b))
        except RedisError as exc:
            self._count("redis_errors_total", op="cache_delete_pattern")
            self._count("cache_errors_total", op="delete_pattern")
            log.warning("Redis no disponible en cache_delete_pattern (%s)", type(exc).__name__)
            return removed
        except RedisUnavailable:
            self._count("cache_errors_total", op="delete_pattern")
            return removed
        if self.metrics and removed:
            self.metrics.inc("cache_invalidations_total", removed)
        return removed

    # ------------------------------------------------- revocación de JWT (crítica)
    def revoke_jti(self, jti, ttl_seconds):
        """Marca el jti como revocado hasta que el token habría expirado de todos modos."""
        ttl = max(int(ttl_seconds), 1)
        self._call("revoke_jti", lambda: self._r.set(KEY_REVOKED + jti, "1", ex=ttl))

    def is_revoked(self, jti):
        return bool(self._call("is_revoked", lambda: self._r.exists(KEY_REVOKED + jti), retries=1))

    # --------------------------------------------------------- sesión (crítica)
    def session_put(self, sid, data, ttl_seconds):
        payload = json.dumps(data, default=_json_default)
        self._call("session_put", lambda: self._r.set(KEY_SESSION + str(sid), payload, ex=max(int(ttl_seconds), 1)))

    def session_get(self, sid):
        raw = self._call("session_get", lambda: self._r.get(KEY_SESSION + str(sid)), retries=1)
        return json.loads(raw) if raw else None

    def session_update(self, sid, **fields):
        """Actualiza campos sin cambiar el TTL. False si la sesión ya no existe."""
        current = self.session_get(sid)
        if current is None:
            return False
        current.update(fields)
        payload = json.dumps(current, default=_json_default)
        return bool(self._call(
            "session_update", lambda: self._r.set(KEY_SESSION + str(sid), payload, xx=True, keepttl=True)))

    def session_touch(self, sid, ttl_seconds):
        """Renueva la ventana deslizante de la sesión. False si ya no existe."""
        return bool(self._call(
            "session_touch", lambda: self._r.expire(KEY_SESSION + str(sid), max(int(ttl_seconds), 1))))

    def session_delete(self, sid):
        self._call("session_delete", lambda: self._r.delete(KEY_SESSION + str(sid)))

    # ------------------------------------------------- refresh token (crítica)
    def refresh_put(self, token_hash, data, ttl_seconds):
        payload = json.dumps(data, default=_json_default)
        self._call("refresh_put", lambda: self._r.set(KEY_REFRESH + token_hash, payload, ex=max(int(ttl_seconds), 1)))

    def refresh_take(self, token_hash):
        """Lee y BORRA en un solo paso (GETDEL): un refresh token solo sirve una vez."""
        raw = self._call("refresh_take", lambda: self._r.getdel(KEY_REFRESH + token_hash))
        return json.loads(raw) if raw else None

    def refresh_delete(self, token_hash):
        self._call("refresh_delete", lambda: self._r.delete(KEY_REFRESH + token_hash))

    # ------------------------------------------------------ candados (críticos)
    @contextmanager
    def lock(self, name, ttl_seconds=10):
        key = KEY_LOCK + name
        token = secrets.token_hex(8)
        acquired = self._call("lock", lambda: self._r.set(key, token, nx=True, ex=max(int(ttl_seconds), 1)))
        if not acquired:
            self._count("lock_contention_total")
            raise LockNotAcquired(name)
        try:
            yield
        finally:
            self._release(key, token)

    def _release(self, key, token):
        """Solo borra el candado si sigue siendo nuestro (si expiró y otro lo tomó, no lo toca)."""
        try:
            with self._r.pipeline() as pipe:
                pipe.watch(key)
                if pipe.get(key) == token:
                    pipe.multi()
                    pipe.delete(key)
                    pipe.execute()
        except RedisError as exc:
            # El candado expirará solo por su TTL; no se propaga para no ocultar el resultado real.
            log.warning("No se pudo liberar el candado %s (%s)", key, type(exc).__name__)

    # --------------------------------------------- idempotencia (crítica)
    @staticmethod
    def idem_key(namespace, key):
        return f"{namespace}:{key}"

    def idem_claim(self, namespace, key, ttl_seconds):
        """True si esta petición es la primera con esa clave; False si ya existía (en curso o terminada)."""
        full = self.idem_key(namespace, key)
        payload = json.dumps({"state": "pending"})
        return bool(self._call("idem_claim", lambda: self._r.set(full, payload, nx=True, ex=max(int(ttl_seconds), 1))))

    def idem_complete(self, namespace, key, result, ttl_seconds):
        full = self.idem_key(namespace, key)
        payload = json.dumps({"state": "done", "result": result}, default=_json_default)
        self._call("idem_complete", lambda: self._r.set(full, payload, ex=max(int(ttl_seconds), 1)))

    def idem_release(self, namespace, key):
        """Libera la reserva si la operación falló (así el cliente puede reintentar con la misma clave)."""
        full = self.idem_key(namespace, key)
        self._call("idem_release", lambda: self._r.delete(full))

    def idem_get(self, namespace, key):
        raw = self._call("idem_get", lambda: self._r.get(self.idem_key(namespace, key)), retries=1)
        return json.loads(raw) if raw else None
