"""Despacho de operaciones SOAP: parsea el Envelope, valida, llama a db/ y
construye la respuesta — todo con xml.etree.ElementTree (docs/CONTRATO_DISENO.md §7).

Orden de validación (mismo criterio en las cuatro operaciones): primero
se valida forma/enums del request (nunca toca BD), y solo si eso pasa se
llama a db/. Esto es lo que garantiza que ModeloInvalido/ValidacionFallida
nunca ejecuten SQL, tal como exige la tabla de Fault del contrato.
"""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import timezone

from db import connection, errors as db_errors, repository
from soap import envelope, faults, security

logger = logging.getLogger(__name__)

# Mismo criterio que ck_clasificadores_correo_formato en sql/soap_module.sql.
CORREO_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MODELOS_VALIDOS = {"IaaS", "PaaS", "SaaS", "FaaS"}


# --------------------------------------------------------------------
# Helpers de validación de campos de entrada
# --------------------------------------------------------------------

def _require_text(operation_el, local_name):
    valor = envelope.get_text(operation_el, local_name)
    if valor is None or valor.strip() == "":
        raise faults.ValidacionFallidaError(f"El campo '{local_name}' es obligatorio.")
    return valor.strip()


def _require_long(operation_el, local_name):
    texto = _require_text(operation_el, local_name)
    try:
        return int(texto)
    except ValueError:
        raise faults.ValidacionFallidaError(f"El campo '{local_name}' debe ser un número entero.")


def _validar_correo(correo):
    if not CORREO_RE.match(correo):
        raise faults.ValidacionFallidaError("El correo indicado no tiene un formato válido.")


def _format_datetime(dt):
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------
# Handlers por operación (nombres = local-name del elemento raíz del Body)
# --------------------------------------------------------------------

def _handle_obtener_conceptos_pendientes(operation_el, header_el, remote_addr):
    filtro_correo = envelope.get_text(operation_el, "filtroCorreo")
    filtro_categoria = envelope.get_text(operation_el, "filtroCategoria")

    if filtro_correo is not None and filtro_correo.strip() == "":
        filtro_correo = None
    if filtro_categoria is not None and filtro_categoria.strip() == "":
        filtro_categoria = None
    if filtro_correo:
        _validar_correo(filtro_correo)

    with connection.get_connection() as conn:
        conceptos, total = repository.listar_conceptos_pendientes(
            conn, filtro_correo, filtro_categoria
        )

    response_el = envelope.make_element("ObtenerConceptosPendientesResponse")
    for c in conceptos:
        concepto_el = envelope.make_subelement(response_el, "concepto")
        envelope.set_text(concepto_el, "bookId", str(c["book_id"]))
        envelope.set_text(concepto_el, "isbn", c["isbn"])
        envelope.set_text(concepto_el, "tituloLibro", c["titulo_libro"])
        envelope.set_text(concepto_el, "categoria", c["categoria"])
        envelope.set_text(concepto_el, "conceptoId", str(c["concepto_id"]))
        envelope.set_text(concepto_el, "concepto", c["concepto"])
        envelope.set_text(concepto_el, "definicion", c["definicion"])
    envelope.set_text(response_el, "total", str(total))
    return response_el


def _handle_registrar_clasificacion(operation_el, header_el, remote_addr):
    nombre = _require_text(operation_el, "nombre")
    apellidos = _require_text(operation_el, "apellidos")
    correo = _require_text(operation_el, "correo")
    book_id = _require_long(operation_el, "bookId")
    concepto_id = _require_long(operation_el, "conceptoId")
    modelo_cloud = _require_text(operation_el, "modeloCloud")
    tipo_cliente = _require_text(operation_el, "tipoCliente")

    _validar_correo(correo)
    if modelo_cloud not in MODELOS_VALIDOS:
        raise faults.ModeloInvalidoError(
            f"'{modelo_cloud}' no es un modeloCloud válido "
            "(use IaaS, PaaS, SaaS o FaaS)."
        )

    with connection.get_connection() as conn:
        try:
            resultado = repository.registrar_clasificacion(
                conn,
                nombre=nombre,
                apellidos=apellidos,
                correo=correo,
                book_id=book_id,
                concepto_id=concepto_id,
                modelo_cloud=modelo_cloud,
                tipo_cliente=tipo_cliente,
                ip_origen=remote_addr,
            )
        except db_errors.ConceptoInexistenteError as exc:
            raise faults.ConceptoInexistenteError(str(exc)) from exc
        except db_errors.ClasificacionDuplicadaError as exc:
            raise faults.ClasificacionDuplicadaError(str(exc)) from exc

    response_el = envelope.make_element("RegistrarClasificacionResponse")
    envelope.set_text(response_el, "clasificacionId", str(resultado["clasificacion_id"]))
    envelope.set_text(response_el, "modeloCloud", resultado["modelo_cloud"])
    envelope.set_text(response_el, "clasificadoEn", _format_datetime(resultado["clasificado_en"]))
    envelope.set_text(response_el, "mensaje", "Clasificación registrada correctamente.")
    return response_el


def _handle_obtener_progreso_usuario(operation_el, header_el, remote_addr):
    correo = _require_text(operation_el, "correo")
    _validar_correo(correo)

    with connection.get_connection() as conn:
        progreso = repository.obtener_progreso_usuario(conn, correo)

    response_el = envelope.make_element("ObtenerProgresoUsuarioResponse")
    envelope.set_text(response_el, "correo", correo)
    envelope.set_text(response_el, "totalConceptos", str(progreso["total_conceptos"]))
    envelope.set_text(response_el, "totalClasificados", str(progreso["total_clasificados"]))
    envelope.set_text(response_el, "totalPendientes", str(progreso["total_pendientes"]))
    envelope.set_text(
        response_el, "porcentajeCompletado", str(progreso["porcentaje_completado"])
    )
    return response_el


def _handle_obtener_estadisticas_por_modelo(operation_el, header_el, remote_addr):
    with connection.get_connection() as conn:
        security.validar_header(header_el, conn)
        estadisticas, total_general = repository.obtener_estadisticas_por_modelo(conn)

    response_el = envelope.make_element("ObtenerEstadisticasPorModeloResponse")
    for e in estadisticas:
        est_el = envelope.make_subelement(response_el, "estadistica")
        envelope.set_text(est_el, "modeloCloud", e["modelo_cloud"])
        envelope.set_text(est_el, "totalClasificaciones", str(e["total"]))
        envelope.set_text(est_el, "porcentaje", str(e["porcentaje"]))
    envelope.set_text(response_el, "totalGeneral", str(total_general))
    return response_el


OPERATIONS = {
    "ObtenerConceptosPendientesRequest": _handle_obtener_conceptos_pendientes,
    "RegistrarClasificacionRequest": _handle_registrar_clasificacion,
    "ObtenerProgresoUsuarioRequest": _handle_obtener_progreso_usuario,
    "ObtenerEstadisticasPorModeloRequest": _handle_obtener_estadisticas_por_modelo,
}


def handle_request(raw_body: bytes, remote_addr=None):
    """Punto de entrada único llamado desde app.py (POST /soap).

    Devuelve (response_bytes, http_status). Nunca lanza: cualquier
    excepción se traduce a un SOAP Fault antes de devolver el control.
    """
    try:
        try:
            header_el, body_el = envelope.parse_envelope(raw_body)
        except (ET.ParseError, envelope.EnvelopeError) as exc:
            raise faults.XMLInvalidoError(
                "El XML recibido no es un mensaje SOAP válido."
            ) from exc

        operation_el = next(iter(body_el), None)
        if operation_el is None:
            raise faults.XMLInvalidoError("El Body del mensaje SOAP está vacío.")

        local_name = operation_el.tag.split("}", 1)[-1]
        handler = OPERATIONS.get(local_name)
        if handler is None:
            raise faults.XMLInvalidoError(f"Operación SOAP desconocida: '{local_name}'.")

        response_el = handler(operation_el, header_el, remote_addr)
        response_bytes = envelope.build_envelope([response_el])
        return response_bytes, 200

    except faults.SoapFaultError as exc:
        logger.warning("SOAP Fault [%s]: %s", exc.codigo, exc.mensaje)
        return faults.build_fault_bytes(exc), exc.http_status
    except Exception:
        # Cualquier otra excepción (BD caída, bug no previsto, etc.): el
        # detalle real SOLO va al log; al cliente solo un mensaje genérico.
        logger.exception("Error interno no controlado procesando una petición SOAP.")
        fallback = faults.ErrorInternoError(
            "Error interno del servicio, intente más tarde."
        )
        return faults.build_fault_bytes(fallback), fallback.http_status
