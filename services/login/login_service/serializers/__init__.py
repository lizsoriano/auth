from flask import Response, request

from ..errors import ApiError
from .json_serializer import to_json
from .xml_serializer import to_xml

FORMATS = ("xml", "json")
DEFAULT_FORMAT = "xml"
MIMETYPES = {"xml": "application/xml", "json": "application/json"}


def requested_format():
    """Devuelve 'xml' (por defecto) o 'json'; cualquier otro valor es un 400."""
    value = request.args.get("format")
    if value is None or value.strip() == "":
        return DEFAULT_FORMAT
    value = value.strip().lower()
    if value not in FORMATS:
        raise ApiError("invalid_format", "El parámetro format debe ser 'xml' o 'json'", 400)
    return value


def _safe_format():
    try:
        return requested_format()
    except ApiError:
        return DEFAULT_FORMAT


def render(payload, status=200, fmt=None):
    fmt = fmt or _safe_format()
    if fmt == "json":
        body = to_json(payload)
    else:
        body = '<?xml version="1.0" encoding="UTF-8"?>\n' + to_xml(payload) + "\n"
    return Response(body, status=status, mimetype=MIMETYPES[fmt])


def error_payload(code, message, details=None):
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}
