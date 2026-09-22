"""Construcción de SOAP Fault según docs/CONTRATO_DISENO.md §4.

Regla dura: el faultstring/detail que ve el cliente NUNCA contiene stack
trace, ruta de archivo, contraseña, cadena de conexión ni el SQL
ejecutado. El detalle técnico real va únicamente a logging (ver
soap/service.py, que loguea la excepción original antes de construir el
Fault genérico).

Nota de diseño: el ejemplo de docs/CONTRATO_DISENO.md §4 usa el prefijo
"lib" para el namespace urn:library-classifier dentro de <detail>. Este
código usa consistentemente el prefijo "tns" (ya registrado en
envelope.py para ese mismo namespace) en todo el documento, Fault
incluido. Es equivalente por especificación XML: lo que importa para un
cliente SOAP es el namespace URI (urn:library-classifier), no la letra
del prefijo — usar un único prefijo en todo el documento evita namespace
declarations redundantes y mantiene el código más simple.
"""
import xml.etree.ElementTree as ET

from soap.envelope import SOAP_ENV_NS, TNS, qname


class SoapFaultError(Exception):
    """Base de todos los errores que se traducen 1:1 a un SOAP Fault."""

    faultcode = "soap:Client"
    codigo = "ErrorInterno"
    http_status = 500

    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


class ConceptoInexistenteError(SoapFaultError):
    codigo = "ConceptoInexistente"
    http_status = 400


class ModeloInvalidoError(SoapFaultError):
    codigo = "ModeloInvalido"
    http_status = 400


class ValidacionFallidaError(SoapFaultError):
    codigo = "ValidacionFallida"
    http_status = 400


class ClasificacionDuplicadaError(SoapFaultError):
    codigo = "ClasificacionDuplicada"
    http_status = 409


class XMLInvalidoError(SoapFaultError):
    codigo = "XMLInvalido"
    http_status = 400


class AutenticacionFallidaError(SoapFaultError):
    codigo = "AutenticacionFallida"
    http_status = 401


class ErrorInternoError(SoapFaultError):
    faultcode = "soap:Server"
    codigo = "ErrorInterno"
    http_status = 500


def build_fault_bytes(exc: SoapFaultError) -> bytes:
    """Serializa un SoapFaultError a un soap:Envelope con soap:Fault.

    faultcode/faultstring/detail van sin namespace (elementos hijos de
    Fault, tal como exige SOAP 1.1 — es la única excepción a "todo va con
    namespace" en este proyecto, porque así lo define el propio estándar
    SOAP, no una decisión nuestra).
    """
    envelope_el = ET.Element(qname(SOAP_ENV_NS, "Envelope"))
    body_el = ET.SubElement(envelope_el, qname(SOAP_ENV_NS, "Body"))
    fault_el = ET.SubElement(body_el, qname(SOAP_ENV_NS, "Fault"))

    faultcode_el = ET.SubElement(fault_el, "faultcode")
    faultcode_el.text = exc.faultcode

    faultstring_el = ET.SubElement(fault_el, "faultstring")
    faultstring_el.text = exc.mensaje

    detail_el = ET.SubElement(fault_el, "detail")
    error_el = ET.SubElement(detail_el, qname(TNS, "Error"))
    codigo_el = ET.SubElement(error_el, qname(TNS, "codigo"))
    codigo_el.text = exc.codigo

    # Único caso donde el contrato pide exponer, además, el HTTP status
    # equivalente dentro del detail (docs/CONTRATO_DISENO.md §4, fila
    # "Clasificación duplicada").
    if exc.codigo == "ClasificacionDuplicada":
        http_el = ET.SubElement(error_el, qname(TNS, "httpStatusEquivalente"))
        http_el.text = str(exc.http_status)

    return ET.tostring(envelope_el, encoding="utf-8", xml_declaration=True)
