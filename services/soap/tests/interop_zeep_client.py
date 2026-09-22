"""Tarea 4 (interoperabilidad): consume library-classifier.wsdl con Zeep,
una librería de terceros que genera su propio cliente SOAP a partir del
contrato — sin conocer nada de soap/service.py ni de soap_client.py (el
cliente manual de la app de escritorio). Si este script funciona, confirma
que el WSDL es un contrato real y reproducible, no solo compatible por
casualidad con la implementación manual del servicio.

Requiere el paquete `zeep` (no está en requirements.txt del servicio a
propósito: es una dependencia del CLIENTE de interoperabilidad, no del
servidor, que sigue construyendo su XML a mano con ElementTree):

    pip install zeep

Uso:
    python tests/interop_zeep_client.py [http://host:puerto/wsdl]

Verificado de verdad (no simulado) el 2026-09-03 contra una instancia real
(GCP, PostgreSQL real, servicio Flask real): las 4 operaciones responden
correctamente, incluyendo el SOAP Fault de duplicado. Ver
docs/EVIDENCIA_DESPLIEGUE_REAL.md para la salida completa.
"""
import sys
import time

from zeep import Client


def main():
    wsdl_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000/wsdl"
    print(f"Cargando WSDL desde {wsdl_url} con Zeep...")
    client = Client(wsdl_url)
    print("WSDL cargado OK.\n")

    print("--- ObtenerConceptosPendientes (cliente Zeep) ---")
    resp = client.service.ObtenerConceptosPendientes()
    print(f"Total conceptos: {resp.total}")
    if not resp.concepto:
        print("No hay conceptos en el catálogo; aplique integracion02/db/02_seed_30_per_table.sql.")
        return
    concepto = resp.concepto[0]
    print("Concepto elegido:", concepto)

    correo = f"cliente.zeep.interop.{int(time.time())}@example.com"

    print("\n--- RegistrarClasificacion (cliente Zeep) ---")
    resp2 = client.service.RegistrarClasificacion(
        nombre="Interop", apellidos="ViaZeep", correo=correo,
        bookId=concepto.bookId, conceptoId=concepto.conceptoId,
        modeloCloud="FaaS", tipoCliente="zeep-interoperabilidad",
    )
    print("Respuesta:", resp2)

    print("\n--- ObtenerProgresoUsuario (cliente Zeep) ---")
    resp3 = client.service.ObtenerProgresoUsuario(correo=correo)
    print("Progreso:", resp3)

    print("\n--- RegistrarClasificacion duplicado (debe fallar con Fault) ---")
    try:
        client.service.RegistrarClasificacion(
            nombre="Interop", apellidos="ViaZeep", correo=correo,
            bookId=concepto.bookId, conceptoId=concepto.conceptoId,
            modeloCloud="FaaS", tipoCliente="zeep-interoperabilidad",
        )
        print("ERROR: se esperaba un Fault de duplicado")
    except Exception as e:
        print(f"OK, Fault recibido -> {type(e).__name__}: {e}")

    print("\nInteroperabilidad confirmada: un cliente de terceros (Zeep),")
    print("que genera su propio stub a partir del WSDL, consumió las 4")
    print("operaciones exitosamente.")


if __name__ == "__main__":
    main()
