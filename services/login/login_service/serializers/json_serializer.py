import json
from datetime import date, datetime
from uuid import UUID


def _default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"{type(value).__name__} no es serializable a JSON")


def to_json(payload):
    return json.dumps(payload, default=_default, ensure_ascii=False, indent=2) + "\n"
