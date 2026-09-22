"""Helpers reutilizables para construir/leer Envelope, Header y Body SOAP.

Únicamente xml.etree.ElementTree — nada de Spyne/Zeep en el servidor
(docs/CONTRATO_DISENO.md §7). set_text() es la única forma en que este
proyecto escribe datos de usuario dentro de un elemento XML: al asignar
Element.text, ElementTree escapa automáticamente '<', '>', '&', etc.,
así que nunca hay concatenación insegura de XML con datos de entrada.
"""
import xml.etree.ElementTree as ET

SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
TNS = "urn:library-classifier"
WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"

ET.register_namespace("soap", SOAP_ENV_NS)
ET.register_namespace("tns", TNS)
ET.register_namespace("wsse", WSSE_NS)
ET.register_namespace("wsu", WSU_NS)


class EnvelopeError(Exception):
    """El XML recibido no tiene la forma de un soap:Envelope válido
    (raíz incorrecta, falta soap:Body, etc.)."""


def qname(ns, local_name):
    """Nombre calificado en la notación que usa ElementTree: '{ns}local'.

    ns=None -> devuelve local_name tal cual (sin namespace). El WSDL
    (wsdl/library-classifier.wsdl) no declara elementFormDefault="qualified"
    en su xsd:schema, así que por la especificación XSD el valor por
    defecto es "unqualified": el elemento RAÍZ de cada mensaje (p. ej.
    tns:RegistrarClasificacionRequest) sí va calificado porque los
    elementos globales siempre lo están, pero sus hijos locales (nombre,
    correo, bookId, etc.) van SIN namespace. Un cliente generado a partir
    del WSDL (p. ej. con Zeep, Tarea 4 de interoperabilidad) construye el
    mensaje exactamente así — de ahí que get_child/get_text/make_subelement/
    set_text para campos del body deban llamarse con ns=None.
    """
    if ns is None:
        return local_name
    return f"{{{ns}}}{local_name}"


def parse_envelope(raw_bytes):
    """Parsea un mensaje SOAP entrante.

    Devuelve (header_el, body_el). header_el puede ser None (soap:Header
    es opcional). Puede lanzar xml.etree.ElementTree.ParseError (XML mal
    formado) o EnvelopeError (XML válido pero no es un Envelope SOAP) —
    ambos los traduce soap/service.py a un Fault lib:XMLInvalido, sin
    tocar nunca la base de datos.
    """
    root = ET.fromstring(raw_bytes)
    if root.tag != qname(SOAP_ENV_NS, "Envelope"):
        raise EnvelopeError("La raíz del documento no es soap:Envelope.")
    header_el = root.find(qname(SOAP_ENV_NS, "Header"))
    body_el = root.find(qname(SOAP_ENV_NS, "Body"))
    if body_el is None:
        raise EnvelopeError("El Envelope no contiene soap:Body.")
    return header_el, body_el


def make_element(local_name, ns=TNS):
    return ET.Element(qname(ns, local_name))


def make_subelement(parent, local_name, ns=None):
    """ns=None por defecto: los hijos de un elemento de mensaje son
    locales/unqualified salvo que se pase explícitamente otro namespace
    (p. ej. ns=WSSE_NS para cabeceras WS-Security). Ver docstring de
    qname()."""
    return ET.SubElement(parent, qname(ns, local_name))


def set_text(parent, local_name, value, ns=None):
    """Crea un sub-elemento <local_name>value</local_name> (sin namespace
    por defecto — ver qname()).

    value se asigna a .text, así que ElementTree lo escapa automáticamente:
    nunca es seguro (ni necesario) construir XML concatenando strings con
    datos de usuario.
    """
    el = ET.SubElement(parent, qname(ns, local_name))
    el.text = value
    return el


def get_child(parent, local_name, ns=None):
    if parent is None:
        return None
    return parent.find(qname(ns, local_name))


def get_text(parent, local_name, ns=None):
    el = get_child(parent, local_name, ns)
    if el is None or el.text is None:
        return None
    return el.text


def build_envelope(body_children):
    """Construye <soap:Envelope><soap:Body>...</soap:Body></soap:Envelope>
    a partir de una lista de elementos ya construidos, y lo serializa a
    bytes UTF-8 con declaración XML."""
    envelope_el = ET.Element(qname(SOAP_ENV_NS, "Envelope"))
    body_el = ET.SubElement(envelope_el, qname(SOAP_ENV_NS, "Body"))
    for child in body_children:
        body_el.append(child)
    return ET.tostring(envelope_el, encoding="utf-8", xml_declaration=True)
