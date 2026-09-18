from datetime import date, datetime
from xml.etree.ElementTree import Element, SubElement, indent, tostring


def _text(value):
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
        parent.text = _text(value)


def to_xml(payload, root_name="response"):
    root = Element(root_name)
    _build(root, payload)
    indent(root)
    return tostring(root, encoding="unicode", xml_declaration=False)
