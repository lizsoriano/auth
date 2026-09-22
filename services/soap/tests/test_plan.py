"""Plan de pruebas ejecutable para library_soap_service.

Manda peticiones SOAP reales a http://127.0.0.1:5000/soap usando SOLO la
librería estándar (http.client + xml.etree.ElementTree) — no asume que
'requests' esté instalado.

Requisitos para correr esto:
  1. library_db poblada con integracion02/db/00_create_database.sql a
     06_views.sql (en ese orden).
  2. sql/soap_module.sql ejecutado encima de esa misma base.
  3. .env configurado (copiado de .env.example) con DATABASE_URL
     apuntando a soap_service_user.
  4. El servicio corriendo: python app.py

Casos cubiertos (ver docs/CONTRATO_DISENO.md §4 para el detalle de cada
Fault y qué HTTP status le corresponde):
  P01 - ObtenerConceptosPendientes sin filtro -> HTTP 200, respuesta bien formada.
  P02 - RegistrarClasificacion con datos válidos -> HTTP 200, clasificación creada.
  N01 - Repetir exactamente la misma clasificación -> HTTP 409, lib:ClasificacionDuplicada.
  N02 - conceptoId inexistente para ese libro -> HTTP 400, lib:ConceptoInexistente.
  N03 - modeloCloud fuera de IaaS/PaaS/SaaS/FaaS -> HTTP 400, lib:ModeloInvalido.

Este archivo NO se ejecutó en el entorno donde se escribió (sandbox sin
PostgreSQL disponible) — queda listo para correr en la máquina del
estudiante con:  python tests/test_plan.py
"""
import http.client
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from soap import envelope  # noqa: E402  (solo depende de la librería estándar)

HOST = "127.0.0.1"
PORT = 5000
TIMEOUT = 10

_resultados = []


def _post_soap(body_children, soap_action):
    request_bytes = envelope.build_envelope(body_children)
    conn = http.client.HTTPConnection(HOST, PORT, timeout=TIMEOUT)
    try:
        conn.request(
            "POST",
            "/soap",
            body=request_bytes,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"{soap_action}"',
            },
        )
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data
    finally:
        conn.close()


def _reportar(caso, ok, detalle):
    estado = "PASS" if ok else "FAIL"
    _resultados.append(ok)
    print(f"[{estado}] {caso}: {detalle}")


def _fault_codigo(body_xml):
    try:
        root = ET.fromstring(body_xml)
    except ET.ParseError:
        return None
    fault = root.find(f".//{{{envelope.SOAP_ENV_NS}}}Fault")
    if fault is None:
        return None
    detail = fault.find("detail")
    if detail is None:
        return None
    codigo_el = detail.find(f".//{{{envelope.TNS}}}codigo")
    return codigo_el.text if codigo_el is not None else None


def obtener_conceptos(filtro_correo=None):
    req = envelope.make_element("ObtenerConceptosPendientesRequest")
    if filtro_correo:
        envelope.set_text(req, "filtroCorreo", filtro_correo)
    return _post_soap([req], "urn:library-classifier#ObtenerConceptosPendientes")


def registrar_clasificacion(correo, book_id, concepto_id, modelo_cloud):
    req = envelope.make_element("RegistrarClasificacionRequest")
    envelope.set_text(req, "nombre", "Prueba")
    envelope.set_text(req, "apellidos", "Automatizada")
    envelope.set_text(req, "correo", correo)
    envelope.set_text(req, "bookId", str(book_id))
    envelope.set_text(req, "conceptoId", str(concepto_id))
    envelope.set_text(req, "modeloCloud", modelo_cloud)
    envelope.set_text(req, "tipoCliente", "plan-de-pruebas")
    return _post_soap([req], "urn:library-classifier#RegistrarClasificacion")


def _resumen_final():
    total = len(_resultados)
    exitosos = sum(1 for r in _resultados if r)
    print(f"\nResumen: {exitosos}/{total} pruebas en PASS.")
    if total == 0 or exitosos < total:
        sys.exit(1)


def main():
    correo_prueba = f"pruebas.soap.{int(time.time())}@example.com"

    # --- P01: catálogo completo (sin filtro) --------------------------
    try:
        status, data = obtener_conceptos()
        root = ET.fromstring(data)
        response_el = root.find(f".//{{{envelope.TNS}}}ObtenerConceptosPendientesResponse")
        ok = status == 200 and response_el is not None
        _reportar("P01 ObtenerConceptosPendientes (sin filtro)", ok, f"HTTP {status}")
    except Exception as exc:
        _reportar("P01 ObtenerConceptosPendientes (sin filtro)", False, f"excepción: {exc}")
        response_el = None

    if response_el is None:
        print(
            "\nNo se pudo obtener el catálogo de conceptos pendientes; se aborta "
            "el resto del plan. Verifique que el servicio esté corriendo "
            "(python app.py) y que la base de datos esté poblada."
        )
        _resumen_final()
        return

    conceptos = response_el.findall(f"{{{envelope.TNS}}}concepto")
    if not conceptos:
        print(
            "\nEl catálogo de conceptos pendientes está vacío; no hay datos de "
            "prueba para P02/N01/N02/N03. Verifique que "
            "integracion02/db/02_seed_30_per_table.sql se haya ejecutado."
        )
        _resumen_final()
        return

    primero = conceptos[0]
    book_id = envelope.get_text(primero, "bookId")
    concepto_id = envelope.get_text(primero, "conceptoId")

    # --- P02: registrar una clasificación válida -----------------------
    try:
        status, data = registrar_clasificacion(correo_prueba, book_id, concepto_id, "SaaS")
        ok = status == 200 and b"clasificacionId" in data
        _reportar("P02 RegistrarClasificacion (datos válidos)", ok, f"HTTP {status}")
    except Exception as exc:
        _reportar("P02 RegistrarClasificacion (datos válidos)", False, f"excepción: {exc}")

    # --- N01: repetir exactamente la misma clasificación -> 409 --------
    try:
        status, data = registrar_clasificacion(correo_prueba, book_id, concepto_id, "SaaS")
        codigo = _fault_codigo(data)
        ok = status == 409 and codigo == "ClasificacionDuplicada"
        _reportar(
            "N01 RegistrarClasificacion (duplicado)", ok, f"HTTP {status}, codigo={codigo}"
        )
    except Exception as exc:
        _reportar("N01 RegistrarClasificacion (duplicado)", False, f"excepción: {exc}")

    # --- N02: conceptoId inexistente para ese libro -> 400 --------------
    try:
        correo_n02 = f"pruebas.soap.n02.{int(time.time())}@example.com"
        status, data = registrar_clasificacion(correo_n02, book_id, "999999999", "SaaS")
        codigo = _fault_codigo(data)
        ok = status == 400 and codigo == "ConceptoInexistente"
        _reportar(
            "N02 RegistrarClasificacion (concepto inexistente)",
            ok,
            f"HTTP {status}, codigo={codigo}",
        )
    except Exception as exc:
        _reportar("N02 RegistrarClasificacion (concepto inexistente)", False, f"excepción: {exc}")

    # --- N03: modeloCloud fuera de enum -> 400 ---------------------------
    try:
        correo_n03 = f"pruebas.soap.n03.{int(time.time())}@example.com"
        status, data = registrar_clasificacion(correo_n03, book_id, concepto_id, "Invalido")
        codigo = _fault_codigo(data)
        ok = status == 400 and codigo == "ModeloInvalido"
        _reportar(
            "N03 RegistrarClasificacion (modeloCloud inválido)",
            ok,
            f"HTTP {status}, codigo={codigo}",
        )
    except Exception as exc:
        _reportar("N03 RegistrarClasificacion (modeloCloud inválido)", False, f"excepción: {exc}")

    _resumen_final()


if __name__ == "__main__":
    main()
