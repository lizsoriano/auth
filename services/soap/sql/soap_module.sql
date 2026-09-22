-- sql/soap_module.sql
-- Tablas propias del módulo SOAP de clasificación Cloud.
--
-- No modifica ni referencia con FK de escritura ninguna tabla del monolito
-- salvo lectura vía FOREIGN KEY hacia books/concepts/book_concepts (que ya
-- existen y son propiedad de apps/web-monolito). Este script asume que
-- db/01_schema.sql de integracion02 ya se ejecutó contra la misma base
-- (library_db).
--
-- Ejecutar conectado a library_db:
--   PGPASSWORD=<superusuario> psql -h localhost -U <superusuario> -d library_db -f sql/soap_module.sql
--
-- Compatibilidad: PostgreSQL 13+ (mismo motor que integracion02/db).

BEGIN;

-- ---------------------------------------------------------------------
-- clasificadores: identidad de la persona que usa un cliente SOAP para
-- clasificar. NO es la tabla users del monolito (esa es para el login
-- web administrativo; esta es un registro ligero, sin contraseña, propio
-- del ejercicio SOAP — ver docs/CONTRATO_DISENO.md, decisión D-02).
-- ---------------------------------------------------------------------
CREATE TABLE clasificadores (
    clasificador_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre varchar(120) NOT NULL,
    apellidos varchar(150) NOT NULL,
    correo varchar(254) NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_clasificadores_correo UNIQUE (correo),
    CONSTRAINT ck_clasificadores_nombre_no_vacio CHECK (btrim(nombre) <> ''),
    CONSTRAINT ck_clasificadores_apellidos_no_vacio CHECK (btrim(apellidos) <> ''),
    CONSTRAINT ck_clasificadores_correo_formato
        CHECK (correo ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$')
);

-- ---------------------------------------------------------------------
-- clasificaciones_cloud: una fila por (clasificador, libro, concepto).
-- La FK compuesta hacia book_concepts garantiza que el par (book_id,
-- concept_id) exista de verdad como definición real del catálogo — no
-- basta con que el concepto exista suelto, tiene que estar asociado a
-- ese libro (ver book_concepts en db/01_schema.sql de integracion02).
-- ---------------------------------------------------------------------
CREATE TABLE clasificaciones_cloud (
    clasificacion_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clasificador_id bigint NOT NULL,
    book_id bigint NOT NULL,
    concept_id bigint NOT NULL,
    modelo_cloud varchar(4) NOT NULL,
    clasificado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cliente_tipo varchar(60),
    ip_origen inet,
    CONSTRAINT fk_clasificaciones_clasificador FOREIGN KEY (clasificador_id)
        REFERENCES clasificadores (clasificador_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_clasificaciones_book_concept FOREIGN KEY (book_id, concept_id)
        REFERENCES book_concepts (book_id, concept_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT ck_clasificaciones_modelo_valido
        CHECK (modelo_cloud IN ('IaaS', 'PaaS', 'SaaS', 'FaaS')),
    -- Regla de negocio explícita del enunciado: el mismo clasificador no
    -- puede registrar dos veces el mismo concepto (de ese libro). Esta es
    -- la restricción que el servicio traduce a SOAP Fault 409.
    CONSTRAINT uq_clasificaciones_sin_duplicado
        UNIQUE (clasificador_id, book_id, concept_id)
);

CREATE INDEX ix_clasificaciones_book_concept
    ON clasificaciones_cloud (book_id, concept_id);
CREATE INDEX ix_clasificaciones_modelo
    ON clasificaciones_cloud (modelo_cloud);

-- ---------------------------------------------------------------------
-- clientes_servidos: contabiliza peticiones por tipo de cliente SOAP
-- (escritorio Tkinter, cliente generado por interoperabilidad, etc.),
-- no por clasificador individual — un clasificador puede usar varios
-- clientes y un cliente puede servir a varios clasificadores.
-- ---------------------------------------------------------------------
CREATE TABLE clientes_servidos (
    cliente_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo_cliente varchar(60) NOT NULL,
    identificador varchar(150) NOT NULL,
    peticiones_atendidas integer NOT NULL DEFAULT 0,
    primera_peticion timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ultima_peticion timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_clientes_servidos_tipo_id UNIQUE (tipo_cliente, identificador),
    CONSTRAINT ck_clientes_servidos_tipo_no_vacio CHECK (btrim(tipo_cliente) <> ''),
    CONSTRAINT ck_clientes_servidos_identificador_no_vacio
        CHECK (btrim(identificador) <> ''),
    CONSTRAINT ck_clientes_servidos_peticiones_no_negativas
        CHECK (peticiones_atendidas >= 0)
);

-- ---------------------------------------------------------------------
-- soap_service_credenciales: usuarios habilitados para invocar
-- ObtenerEstadisticasPorModelo (WS-Security UsernameToken/PasswordDigest,
-- ver docs/CONTRATO_DISENO.md §5). No tiene relación con la tabla users
-- del monolito ni con clasificadores (son credenciales de "cliente de
-- reportes", no personas clasificando).
--
-- IMPORTANTE: NO se guarda un hash unidireccional (SHA-256, bcrypt, etc.)
-- de la contraseña. El perfil WS-Security PasswordDigest exige que el
-- servidor pueda reconstruir Base64(SHA1(nonce+created+password)), lo
-- que por definición requiere la contraseña real (o un equivalente
-- reversible) del lado servidor — un hash unidireccional es incompatible
-- con ese perfil (si se usa el hash mismo como "password" en la fórmula,
-- ese hash pasa a ser el secreto de autenticación real, ni más ni menos
-- seguro que guardar la contraseña en claro: quien lea esa fila ya puede
-- autenticarse, sin necesidad de la contraseña original — ver
-- docs/CONTRATO_DISENO.md §5 y docs/ENGINEERING_DECISIONS.md ED-07).
--
-- En vez de eso, `password_cifrada` guarda la contraseña cifrada con
-- Fernet (AES simétrico autenticado, paquete `cryptography`) usando una
-- clave maestra que vive SOLO en la variable de entorno WSSE_MASTER_KEY
-- del servidor (nunca en esta base de datos ni en el repositorio). Una
-- fuga de la base de datos por sí sola no permite autenticarse: además
-- hace falta la clave maestra del servidor (defensa en profundidad).
-- ---------------------------------------------------------------------
CREATE TABLE soap_service_credenciales (
    usuario varchar(60) PRIMARY KEY,
    password_cifrada text NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_soap_credenciales_usuario_no_vacio CHECK (btrim(usuario) <> ''),
    CONSTRAINT ck_soap_credenciales_cifrada_no_vacia CHECK (btrim(password_cifrada) <> '')
);

-- Función auxiliar para registrar/incrementar en una sola sentencia desde
-- la capa de acceso a datos (evita un SELECT + INSERT/UPDATE con carrera
-- entre dos peticiones concurrentes del mismo cliente). Sin SECURITY
-- DEFINER propio: solo la invoca fn_registrar_clasificacion (más abajo),
-- que sí es SECURITY DEFINER, así que hereda su contexto de ejecución.
CREATE OR REPLACE FUNCTION fn_registrar_peticion_cliente(
    p_tipo_cliente varchar,
    p_identificador varchar
) RETURNS void
LANGUAGE sql
AS $$
    INSERT INTO clientes_servidos (tipo_cliente, identificador, peticiones_atendidas)
    VALUES (p_tipo_cliente, p_identificador, 1)
    ON CONFLICT (tipo_cliente, identificador)
    DO UPDATE SET
        peticiones_atendidas = clientes_servidos.peticiones_atendidas + 1,
        ultima_peticion = CURRENT_TIMESTAMP;
$$;

-- =======================================================================
-- Vistas y Stored Procedures (Parte 6, punto 12 del enunciado): toda la
-- capa de acceso a datos del servicio pasa por aquí, nunca por SQL suelto
-- construido en Python. Todas las funciones son SECURITY DEFINER: se
-- ejecutan con los privilegios de quien las creó (el superusuario que
-- corre este script), no con los de quien las invoca. Esto permite que
-- soap_service_user NO necesite NINGÚN privilegio directo sobre las
-- tablas (ni las del monolito ni las propias) — ver el bloque de
-- privilegios al final, notablemente más estrecho que en la primera
-- versión de este archivo (ver docs/ENGINEERING_DECISIONS.md ED-11).
-- =======================================================================

-- Vista base: el JOIN completo de un concepto clasificable con su libro y
-- categoría. Solo lectura del monolito, nunca escribe nada.
CREATE OR REPLACE VIEW v_conceptos_clasificables AS
    SELECT bc.book_id, b.isbn, b.title AS titulo_libro, cat.name AS categoria,
           bc.concept_id, c.name AS concepto, bc.definition AS definicion
    FROM book_concepts bc
    JOIN books b ON b.book_id = bc.book_id
    JOIN categories cat ON cat.category_id = b.category_id
    JOIN concepts c ON c.concept_id = bc.concept_id;

-- ObtenerConceptosPendientes: filtra la vista anterior por categoría y por
-- "no clasificado todavía por ese correo" (si p_correo es NULL, el NOT
-- EXISTS siempre se cumple y devuelve el catálogo completo).
CREATE OR REPLACE FUNCTION fn_conceptos_pendientes(
    p_correo varchar DEFAULT NULL,
    p_categoria varchar DEFAULT NULL
) RETURNS TABLE (
    book_id bigint, isbn varchar, titulo_libro varchar, categoria varchar,
    concept_id bigint, concepto varchar, definicion text
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT v.book_id, v.isbn, v.titulo_libro, v.categoria,
           v.concept_id, v.concepto, v.definicion
    FROM v_conceptos_clasificables v
    WHERE (p_categoria IS NULL OR v.categoria = p_categoria)
      AND NOT EXISTS (
          SELECT 1 FROM clasificaciones_cloud cc
          JOIN clasificadores cl ON cl.clasificador_id = cc.clasificador_id
          WHERE cl.correo = p_correo
            AND cc.book_id = v.book_id
            AND cc.concept_id = v.concept_id
      )
    ORDER BY v.titulo_libro, v.concepto;
$$;

-- RegistrarClasificacion: la transacción COMPLETA vive aquí (una función
-- PL/pgSQL es atómica — si cualquier excepción no se captura dentro de
-- ella, PostgreSQL revierte automáticamente todo lo que llevaba hecho,
-- incluido el upsert del clasificador). Usa un SQLSTATE propio ('LC001',
-- fuera de los rangos reservados por el estándar SQL y por PostgreSQL)
-- para el caso "concepto inexistente", que db/repository.py distingue
-- del resto de errores; el caso "duplicado" no necesita código propio
-- porque ya lo dispara la propia restricción UNIQUE de la tabla
-- (unique_violation, SQLSTATE 23505 estándar).
CREATE OR REPLACE FUNCTION fn_registrar_clasificacion(
    p_nombre varchar,
    p_apellidos varchar,
    p_correo varchar,
    p_book_id bigint,
    p_concept_id bigint,
    p_modelo_cloud varchar,
    p_tipo_cliente varchar,
    p_ip_origen inet DEFAULT NULL
) RETURNS TABLE (clasificacion_id bigint, clasificado_en timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_clasificador_id bigint;
    v_nombre_existente varchar;
    v_apellidos_existente varchar;
BEGIN
    -- 1. El concepto debe existir para ESE libro (no basta con que exista
    --    suelto en concepts).
    IF NOT EXISTS (
        SELECT 1 FROM book_concepts
        WHERE book_id = p_book_id AND concept_id = p_concept_id
    ) THEN
        RAISE EXCEPTION 'CONCEPTO_INEXISTENTE'
            USING ERRCODE = 'LC001',
                  DETAIL = format(
                      'No existe el concepto %s para el libro %s.',
                      p_concept_id, p_book_id
                  );
    END IF;

    -- 2. Upsert de clasificador por correo (no pisa nombre/apellidos si
    --    ya existía con datos distintos, solo lo advierte en el log del
    --    servidor de PostgreSQL).
    INSERT INTO clasificadores (nombre, apellidos, correo)
    VALUES (p_nombre, p_apellidos, p_correo)
    ON CONFLICT (correo) DO NOTHING
    RETURNING clasificadores.clasificador_id INTO v_clasificador_id;

    IF v_clasificador_id IS NULL THEN
        SELECT c.clasificador_id, c.nombre, c.apellidos
          INTO v_clasificador_id, v_nombre_existente, v_apellidos_existente
          FROM clasificadores c
          WHERE c.correo = p_correo;
        IF v_nombre_existente <> p_nombre OR v_apellidos_existente <> p_apellidos THEN
            RAISE WARNING
                'Clasificador existente (correo=%) con nombre/apellidos '
                'distintos a los enviados en esta petición; se conserva '
                'el registro existente sin modificar.', p_correo;
        END IF;
    END IF;

    -- 3. Insertar la clasificación. uq_clasificaciones_sin_duplicado
    --    dispara unique_violation aquí mismo si es un duplicado, y
    --    PostgreSQL revierte automáticamente el upsert del paso 2 también
    --    (atomicidad de función, no solo de sentencia).
    RETURN QUERY
    INSERT INTO clasificaciones_cloud
        (clasificador_id, book_id, concept_id, modelo_cloud, cliente_tipo, ip_origen)
    VALUES (v_clasificador_id, p_book_id, p_concept_id, p_modelo_cloud, p_tipo_cliente, p_ip_origen)
    RETURNING clasificaciones_cloud.clasificacion_id, clasificaciones_cloud.clasificado_en;

    -- 4. Contabilizar la petición del cliente (identificador de negocio =
    --    correo, ver docs/CONTRATO_DISENO.md §2.2).
    PERFORM fn_registrar_peticion_cliente(p_tipo_cliente, p_correo);
END;
$$;

-- ObtenerProgresoUsuario: total de conceptos clasificables vs. cuántos
-- clasificó ese correo.
CREATE OR REPLACE FUNCTION fn_progreso_usuario(p_correo varchar)
RETURNS TABLE (
    total_conceptos integer,
    total_clasificados integer,
    total_pendientes integer,
    porcentaje_completado numeric
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_total integer;
    v_clasificados integer;
BEGIN
    SELECT COUNT(*) INTO v_total FROM book_concepts;
    SELECT COUNT(*) INTO v_clasificados
      FROM clasificaciones_cloud cc
      JOIN clasificadores cl ON cl.clasificador_id = cc.clasificador_id
      WHERE cl.correo = p_correo;

    RETURN QUERY SELECT
        v_total,
        v_clasificados,
        v_total - v_clasificados,
        CASE WHEN v_total > 0
             THEN ROUND((v_clasificados::numeric * 100) / v_total, 2)
             ELSE 0.00
        END;
END;
$$;

-- ObtenerEstadisticasPorModelo (Tarea 1, protegida con WS-Security): vista
-- pura, sin parámetros — el caso ideal de "vista" del enunciado. El
-- porcentaje se calcula aquí mismo con una función de ventana, no en
-- Python.
CREATE OR REPLACE VIEW v_estadisticas_por_modelo AS
    SELECT modelo_cloud,
           COUNT(*) AS total,
           ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS porcentaje
    FROM clasificaciones_cloud
    GROUP BY modelo_cloud
    ORDER BY modelo_cloud;

-- ---------------------------------------------------------------------
-- Mínimo privilegio (Parte 4, punto 8): rol de aplicación dedicado para
-- el módulo SOAP. No es superusuario ni el mismo rol que usa
-- apps/web-monolito.
--
-- Con las funciones SECURITY DEFINER de arriba, soap_service_user NO
-- necesita NINGÚN privilegio directo sobre tablas (ni las del monolito
-- ni las propias): todo pasa por EXECUTE en funciones y SELECT en la
-- vista de estadísticas, que es justamente el patrón "la aplicación solo
-- conoce procedimientos almacenados" que pide el enunciado. Ver
-- docs/ENGINEERING_DECISIONS.md ED-11 para la comparación contra la
-- primera versión de este script (que sí otorgaba SELECT/INSERT directo).
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'soap_service_user') THEN
        CREATE ROLE soap_service_user LOGIN PASSWORD 'CAMBIAR_EN_.env_NO_COMMITEAR';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE library_db TO soap_service_user;
GRANT USAGE ON SCHEMA public TO soap_service_user;

-- Único acceso de solo lectura directo a una tabla: las credenciales de
-- reportes, por PK, sin JOIN — no amerita una vista/función propia (ver
-- ED-11 para la justificación de por qué esta sí es una excepción).
GRANT SELECT ON soap_service_credenciales TO soap_service_user;

-- Toda la lógica de negocio pasa por aquí, nunca por acceso directo a tablas.
GRANT EXECUTE ON FUNCTION fn_conceptos_pendientes(varchar, varchar) TO soap_service_user;
GRANT EXECUTE ON FUNCTION fn_registrar_clasificacion(
    varchar, varchar, varchar, bigint, bigint, varchar, varchar, inet
) TO soap_service_user;
GRANT EXECUTE ON FUNCTION fn_progreso_usuario(varchar) TO soap_service_user;
GRANT SELECT ON v_estadisticas_por_modelo TO soap_service_user;

COMMIT;

-- Nota de auditoría (Parte 4, punto 8): soap_service_user NO tiene ningún
-- privilegio DIRECTO sobre books/categories/concepts/book_concepts ni
-- sobre clasificadores/clasificaciones_cloud/clientes_servidos — solo
-- EXECUTE en 3 funciones SECURITY DEFINER y SELECT en 1 vista + 1 tabla
-- de credenciales. NO tiene DELETE en ninguna tabla (ni siquiera
-- indirectamente, ninguna función de este archivo hace DELETE), NO tiene
-- ningún privilegio sobre users/authors/formats/genres/book_authors/
-- book_genres/book_images, y NO puede crear ni alterar objetos (no tiene
-- CREATE en el esquema). Ver docs/CONTRATO_DISENO.md, tabla de auditoría
-- del contrato, para la justificación dato por dato.
