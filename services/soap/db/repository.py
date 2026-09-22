"""Capa de acceso a datos: una función por operación del WSDL.

Reglas duras (docs/CONTRATO_DISENO.md §3, actualizado en ED-11):
  - Ninguna consulta arma JOINs ni INSERTs sueltos en Python: todo pasa
    por las vistas/funciones (Stored Procedures) de sql/soap_module.sql
    (fn_conceptos_pendientes, fn_registrar_clasificacion,
    fn_progreso_usuario, v_estadisticas_por_modelo), tal como exige la
    Parte 6, punto 12 del enunciado. Los únicos parámetros que viajan son
    los argumentos posicionales de cada función — nunca SQL concatenado.
  - fn_registrar_clasificacion es atómica en sí misma (PL/pgSQL): si algo
    falla dentro, PostgreSQL revierte automáticamente todo lo que llevaba
    hecho la función, sin necesitar BEGIN/COMMIT/ROLLBACK explícitos del
    lado de Python para coordinar varias sentencias.
  - Todas las funciones son SECURITY DEFINER: soap_service_user no tiene
    ningún privilegio directo sobre tablas, solo EXECUTE/SELECT sobre
    estos objetos (ver sql/soap_module.sql, bloque de privilegios).
"""
import logging

import psycopg2
from psycopg2 import errors as pg_errors

from db.errors import ClasificacionDuplicadaError, ConceptoInexistenteError

logger = logging.getLogger(__name__)

# SQLSTATE propio que fn_registrar_clasificacion lanza para "concepto
# inexistente" (ver sql/soap_module.sql). psycopg2.errors.lookup() solo
# reconoce los SQLSTATE que psycopg2 ya conoce de antemano (los del
# estándar SQL y los reservados de PL/pgSQL) — para un código custom como
# este, lookup() lanza KeyError en vez de crear una clase dinámica. Por
# eso aquí se captura psycopg2.Error genérico y se compara `.pgcode` a
# mano, que sí refleja el SQLSTATE real que mandó el servidor
# independientemente de si psycopg2 tiene una clase Python para él.
_CODIGO_CONCEPTO_INEXISTENTE = "LC001"


def listar_conceptos_pendientes(conn, filtro_correo=None, filtro_categoria=None):
    """ObtenerConceptosPendientes -> fn_conceptos_pendientes(correo, categoria)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM fn_conceptos_pendientes(%s, %s)",
            (filtro_correo, filtro_categoria),
        )
        filas = cur.fetchall()
    conn.commit()  # solo lectura; cierra la transacción implícita abierta por execute()

    conceptos = [
        {
            "book_id": f[0],
            "isbn": f[1],
            "titulo_libro": f[2],
            "categoria": f[3],
            "concepto_id": f[4],
            "concepto": f[5],
            "definicion": f[6],
        }
        for f in filas
    ]
    return conceptos, len(conceptos)


def registrar_clasificacion(
    conn,
    *,
    nombre,
    apellidos,
    correo,
    book_id,
    concepto_id,
    modelo_cloud,
    tipo_cliente,
    ip_origen=None,
):
    """RegistrarClasificacion -> fn_registrar_clasificacion(...).

    La función de PostgreSQL ya es atómica (ver docstring del módulo);
    aquí solo se traducen sus dos formas de fallo a las excepciones que
    soap/service.py convierte en SOAP Fault.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM fn_registrar_clasificacion(%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    nombre,
                    apellidos,
                    correo,
                    book_id,
                    concepto_id,
                    modelo_cloud,
                    tipo_cliente,
                    ip_origen,
                ),
            )
            clasificacion_id, clasificado_en = cur.fetchone()
        conn.commit()
        return {
            "clasificacion_id": clasificacion_id,
            "modelo_cloud": modelo_cloud,
            "clasificado_en": clasificado_en,
        }
    except pg_errors.UniqueViolation as exc:
        conn.rollback()
        raise ClasificacionDuplicadaError(
            "Ya existe una clasificación registrada por este correo para ese "
            "libro y concepto."
        ) from exc
    except psycopg2.Error as exc:
        conn.rollback()
        if getattr(exc, "pgcode", None) == _CODIGO_CONCEPTO_INEXISTENTE:
            detalle = (
                exc.diag.message_detail
                if exc.diag and exc.diag.message_detail
                else str(exc)
            )
            raise ConceptoInexistenteError(detalle) from exc
        raise
    except Exception:
        conn.rollback()
        raise


def obtener_progreso_usuario(conn, correo):
    """ObtenerProgresoUsuario -> fn_progreso_usuario(correo)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM fn_progreso_usuario(%s)", (correo,))
        total_conceptos, total_clasificados, total_pendientes, porcentaje = cur.fetchone()
    conn.commit()

    return {
        "total_conceptos": total_conceptos,
        "total_clasificados": total_clasificados,
        "total_pendientes": total_pendientes,
        "porcentaje_completado": porcentaje,
    }


def obtener_estadisticas_por_modelo(conn):
    """ObtenerEstadisticasPorModelo -> v_estadisticas_por_modelo (vista pura,
    sin parámetros; el porcentaje ya viene calculado por la vista)."""
    with conn.cursor() as cur:
        cur.execute("SELECT modelo_cloud, total, porcentaje FROM v_estadisticas_por_modelo")
        filas = cur.fetchall()
    conn.commit()

    total_general = sum(total for _, total, _ in filas)
    estadisticas = [
        {"modelo_cloud": modelo, "total": total, "porcentaje": porcentaje}
        for modelo, total, porcentaje in filas
    ]
    return estadisticas, total_general


def obtener_credencial(conn, usuario):
    """Busca una credencial WS-Security por usuario (soap/security.py).

    Devuelve None si no existe (nunca lanza para "no encontrado": es
    soap/security.py quien decide qué Fault genérico mostrar, sin
    revelar si el usuario existe o no).

    Única lectura directa de una tabla en todo este módulo: es una
    consulta de una sola tabla por clave primaria, sin JOIN ni lógica de
    negocio — no amerita una vista o función propia (ver
    docs/ENGINEERING_DECISIONS.md ED-11 para el criterio completo de
    cuándo sí/no se usa un Stored Procedure).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT usuario, password_cifrada FROM soap_service_credenciales WHERE usuario = %s",
            (usuario,),
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    return {"usuario": row[0], "password_cifrada": row[1]}


# --------------------------------------------------------------------
# Actividad en clase: microservicio bilingüe (XML/JSON, ver app.py y
# sql/ejercicio05_extension.sql). Dos funciones nuevas, mismo patrón que
# las de arriba -- una función por operación, todo vía SECURITY DEFINER.
# --------------------------------------------------------------------

def listar_libros(conn):
    """GET /books y GET /books/<isbn> -> fn_listar_libros() (sql/migracion_libros_completo.sql,
    que extiende la version original de sql/ejercicio05_extension.sql con
    stock, publication_year y autor(es))."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT book_id, isbn, title, price, category, stock, publication_year, authors "
            "FROM fn_listar_libros()"
        )
        filas = cur.fetchall()
    conn.commit()
    return [
        {
            "book_id": f[0], "isbn": f[1], "title": f[2], "price": f[3], "category": f[4],
            "stock": f[5], "publication_year": f[6], "authors": f[7],
        }
        for f in filas
    ]


def listar_libros_con_imagenes(conn):
    """Punto 6 de la actividad -> fn_libros_con_imagenes(), agrupado por libro."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT book_id, isbn, title, image_url, is_cover FROM fn_libros_con_imagenes()"
        )
        filas = cur.fetchall()
    conn.commit()

    libros = {}
    for book_id, isbn, title, image_url, is_cover in filas:
        libro = libros.setdefault(
            book_id, {"book_id": book_id, "isbn": isbn, "title": title, "images": []}
        )
        libro["images"].append({"url": image_url, "is_cover": is_cover})
    return list(libros.values())
