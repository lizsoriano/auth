"""Serialización XML (por defecto) o JSON (?format=json), igual que services/login."""
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from flask import Response, request

from .errors import ApiError

FORMATS = ("xml", "json")
DEFAULT_FORMAT = "xml"
MIMETYPES = {"xml": "application/xml", "json": "application/json"}


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"{type(value).__name__} no es serializable a JSON")


def to_json(payload):
    return json.dumps(payload, default=_json_default, ensure_ascii=False, indent=2) + "\n"


def _xml_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _build(parent, value):
    if isinstance(value, dict):
        for key, item in value.items():
            _build(SubElement(parent, str(key)), item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _build(SubElement(parent, "item"), item)
    elif value is not None:
        parent.text = _xml_text(value)


def to_xml(payload, root_name="response"):
    root = Element(root_name)
    _build(root, payload)
    indent(root)
    return tostring(root, encoding="unicode", xml_declaration=False)


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
    response = Response(body, status=status, mimetype=MIMETYPES[fmt])
    response.headers["Cache-Control"] = "no-store"
    return response


def error_payload(code, message, details=None):
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}
