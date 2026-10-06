"""Serialización XML (por defecto) / JSON: vive en library_common para que los 6 servicios respondan igual."""
from library_common.serializers import (  # noqa: F401
    DEFAULT_FORMAT,
    FORMATS,
    MIMETYPES,
    error_payload,
    render,
    requested_format,
    to_json,
    to_xml,
)
