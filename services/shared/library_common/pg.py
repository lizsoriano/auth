"""Acceso a PostgreSQL SOLO por funciones SQL, con el rol de mínimo privilegio de cada servicio.

Cada servicio llama `SELECT * FROM fn_...(%s, ...)`; no tiene permiso sobre ninguna tabla. Los errores de la base
se traducen a ApiError (nunca se devuelve al cliente el texto técnico de PostgreSQL ni el SQL):

* SQLSTATE propios (US001, PD002, PG003...): cada servicio los declara con su status y código; el mensaje en
  español lo escribimos nosotros en la función SQL, así que sí se muestra.
* SQLSTATE genéricos de integridad (23505, 23503, 23514...): mensaje fijo, sin nombres de constraint.
* Todo lo demás: 500 genérico, con el detalle solo en el log.
"""
import logging

from .errors import ApiError

log = logging.getLogger(__name__)

GENERIC_ERRORS = {
    "23505": (409, "conflict", "Ya existe un registro con esos datos."),
    "23503": (409, "reference_conflict",
              "La operación choca con datos relacionados (una referencia no existe o el registro está en uso)."),
    "23514": (400, "validation_error", "Los datos no cumplen las reglas de la base de datos."),
    "23502": (400, "validation_error", "Falta un dato obligatorio."),
    "22P02": (400, "validation_error", "Un dato tiene un formato inválido."),
    "22003": (400, "validation_error", "Un valor numérico está fuera de rango."),
    "22001": (400, "validation_error", "Un texto excede la longitud permitida."),
}


class Pg:
    def __init__(self, url, connect_timeout=5, errors=None):
        self._url = url
        self._timeout = connect_timeout
        self._errors = {**GENERIC_ERRORS, **(errors or {})}

    def query(self, sql, params=()):
        """Ejecuta una consulta y devuelve la lista de filas (dict). Una conexión por llamada, con commit/rollback."""
        import psycopg
        from psycopg.rows import dict_row
        try:
            with psycopg.connect(self._url, connect_timeout=self._timeout, row_factory=dict_row) as conn:
                cur = conn.execute(sql, params)
                return cur.fetchall() if cur.description else []
        except psycopg.OperationalError:
            log.exception("PostgreSQL no disponible")
            raise ApiError("database_unavailable",
                           "El servicio no puede consultar la base de datos en este momento", 503) from None
        except psycopg.Error as exc:
            raise self._translate(exc) from None

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def ping(self):
        self.query("SELECT 1")

    def _translate(self, exc):
        state = getattr(exc, "sqlstate", None)
        mapped = self._errors.get(state)
        if mapped:
            status, code, message = mapped
            if message is None:
                message = (exc.diag.message_primary or "Operación rechazada")
            return ApiError(code, message, status)
        log.exception("Error de PostgreSQL no previsto (SQLSTATE %s)", state)
        return ApiError("internal_error", "Error interno del servidor", 500)
