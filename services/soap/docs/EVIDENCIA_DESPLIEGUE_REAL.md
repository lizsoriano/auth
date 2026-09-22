# Evidencia de despliegue y pruebas reales (2026-09-03)

Este documento reemplaza los `PENDING` de `docs/TEST_PLAN.md` con
resultados obtenidos contra infraestructura real, no simulada. Todo lo
de aquí se ejecutó contra:

- Instancia GCP `maquina-02` (zona `northamerica-south1-c`, proyecto
  `integracion-sistemas-637044`), CentOS Stream 10 — la misma instancia
  donde ya vive el monolito Node.js de `integracion02` (Ejercicio
  Guiado 02), corriendo en paralelo sin modificarse.
- PostgreSQL 16.14 real, base `library_db`, con el esquema del monolito
  (`integracion02/db/01_schema.sql`) y su semilla de 30 filas por tabla
  ya aplicados de antes (30 libros, 30 conceptos, 66 relaciones
  libro-concepto, 20 categorías).
- `sql/soap_module.sql` de este proyecto, aplicado por primera vez contra
  esa base real, sin errores.
- El servicio Flask real (`app.py`) corriendo en `127.0.0.1:5000` dentro
  de la instancia (no expuesto a Internet — se probó todo por SSH, igual
  que el monolito solo escucha en loopback detrás de su reverse proxy).

## 1. Aplicación de `sql/soap_module.sql`

```
BEGIN
CREATE TABLE
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE TABLE
CREATE TABLE
CREATE FUNCTION
DO
GRANT (x8)
COMMIT
```

Sin errores. Confirma que el DDL es válido contra PostgreSQL 16 real, no
solo balanceado sintácticamente.

## 2. Bug real encontrado y corregido: namespaces XML entre cliente y servidor

Al probar el cliente de escritorio real (`soap_client.py`) contra el
servicio real, `RegistrarClasificacion` devolvía
`ValidacionFallida: El campo 'nombre' es obligatorio` a pesar de que el
cliente sí enviaba `nombre`. Causa raíz: el WSDL no declara
`elementFormDefault="qualified"` en su `xsd:schema`, así que por la
especificación XSD el valor por defecto es `unqualified` — el elemento
RAÍZ de cada mensaje (p. ej. `tns:RegistrarClasificacionRequest`) va
calificado porque los elementos globales siempre lo están, pero sus
HIJOS locales (`nombre`, `correo`, `bookId`, etc.) van sin namespace. El
cliente de escritorio lo implementó correctamente desde el principio;
`soap/service.py` (implementado por un proceso distinto en paralelo)
asumía por error que los hijos también venían calificados con `tns:`, y
sus propias pruebas (`tests/test_plan.py`) no lo detectaron porque las
escribió el mismo autor, con el mismo supuesto equivocado de ambos
lados — un caso de manual de por qué una prueba de integración con un
cliente independiente encuentra bugs que una prueba unitaria del mismo
autor no puede ver.

**Corrección aplicada**: `soap/envelope.py` — `get_child`, `get_text`,
`make_subelement` y `set_text` ahora usan `ns=None` (sin calificar) por
defecto; solo `make_element` (el elemento raíz de cada mensaje) sigue
calificado con `tns`. `soap/service.py` no necesitó cambios propios
porque ya llamaba a esos helpers sin pasar `ns` explícito — heredó el
comportamiento correcto automáticamente. Verificado con
`python -m py_compile` y, más importante, con las pruebas reales de las
secciones 3–5 de este documento, corridas ANTES y DESPUÉS del fix:
antes fallaban con el cliente real, después pasan las tres baterías de
prueba (cliente manual, Zeep, y `tests/test_plan.py`).

Esto también significa que, sin este fix, **cualquier cliente generado
estrictamente a partir del WSDL** (como el de la sección 5, Zeep) habría
fallado igual — no era un problema exclusivo de `soap_client.py`.

## 3. `tests/test_plan.py` (casos P01/P02/N01/N02/N03)

```
[PASS] P01 ObtenerConceptosPendientes (sin filtro): HTTP 200
[PASS] P02 RegistrarClasificacion (datos válidos): HTTP 200
[PASS] N01 RegistrarClasificacion (duplicado): HTTP 409, codigo=ClasificacionDuplicada
[PASS] N02 RegistrarClasificacion (concepto inexistente): HTTP 400, codigo=ConceptoInexistente
[PASS] N03 RegistrarClasificacion (modeloCloud inválido): HTTP 400, codigo=ModeloInvalido

Resumen: 5/5 pruebas en PASS.
```

## 4. Caso X01 — XML mal formado

```
curl -X POST -H 'Content-Type: text/xml' --data '<soap:Envelope><soap:Body><roto' http://127.0.0.1:5000/soap

HTTP 400
<soap:Fault><faultcode>soap:Client</faultcode>
<faultstring>El XML recibido no es un mensaje SOAP válido.</faultstring>
<detail><tns:Error><tns:codigo>XMLInvalido</tns:codigo></tns:Error></detail></soap:Fault>
```

## 5. WS-Security (casos WS01/WS02) — `UsernameToken`/`PasswordDigest`

Credencial creada con `scripts/crear_credencial_reportes.py` (usuario
`reportes`), usando `ADMIN_DATABASE_URL` para la conexión administrativa
(ver ED en `docs/ENGINEERING_DECISIONS.md` sobre por qué el script
necesita una conexión aparte de la del servicio).

```
[PASS] WS01 credenciales correctas: HTTP 200 (esperado 200)
[PASS] WS02a password incorrecto: HTTP 401 (esperado 401)
[PASS] WS02b usuario inexistente: HTTP 401 (esperado 401)
[PASS] WS02c digest manipulado: HTTP 401 (esperado 401)

Resumen: 4/4 pruebas en PASS.
```

Esto confirma en la práctica la corrección de seguridad documentada en
ED-07/README §3 ED-04: el servidor descifra `password_cifrada` con
`WSSE_MASTER_KEY` para recuperar la contraseña real y calcular el
digest — nunca compara contra un hash almacenado.

**Caso WS03 (sin cabecera / nonce repetido)**, agregado tras la primera
ronda de pruebas:

```
[PASS] WS03a sin soap:Header: HTTP 401
Primer uso del nonce: HTTP 200 (se espera 200, consumiendo el nonce)
[PASS] WS03b nonce repetido (replay): HTTP 401
```

Confirma que `soap/security.py` rechaza tanto la ausencia total de la
cabecera WS-Security como el reuso de un `wsse:Nonce` ya consumido
dentro de la ventana de tolerancia (protección contra *replay*).

## 6. Cliente de escritorio real (`soap_client.py`) — el mismo código de la GUI

Ejecutado sin Tkinter (llamando directamente a las funciones que la GUI
invoca al hacer clic en sus botones), contra el servicio real:

```
--- obtener_conceptos_pendientes() ---
Total conceptos: 66

--- registrar_clasificacion() camino feliz ---
OK: ResultadoClasificacion(clasificacion_id=3, modelo_cloud='PaaS', ...)

--- registrar_clasificacion() duplicado (debe fallar) ---
OK, Fault esperado -> codigo='ClasificacionDuplicada'
mensaje_amigable='Ya existe una clasificación registrada con este correo para ese concepto.'

--- obtener_progreso_usuario() ---
Progreso: ProgresoUsuario(correo='...', total_conceptos=66, total_clasificados=1,
total_pendientes=65, porcentaje_completado=1.52)
```

## 7. Interoperabilidad real (Tarea 4) — cliente Zeep

`tests/interop_zeep_client.py`, ejecutado contra el WSDL real servido
por `GET /wsdl`:

```
Cargando WSDL desde http://127.0.0.1:5000/wsdl con Zeep...
WSDL cargado OK.

--- ObtenerConceptosPendientes (cliente Zeep) ---
Total conceptos: 66

--- RegistrarClasificacion (cliente Zeep) ---
Respuesta: {'clasificacionId': 5, 'modeloCloud': 'FaaS', 'clasificadoEn': ...,
'mensaje': 'Clasificación registrada correctamente.'}

--- ObtenerProgresoUsuario (cliente Zeep) ---
Progreso: {'correo': '...', 'totalConceptos': 66, 'totalClasificados': 1,
'totalPendientes': 65, 'porcentajeCompletado': Decimal('1.52')}

--- RegistrarClasificacion duplicado (debe fallar con Fault) ---
OK, Fault recibido -> Fault: Ya existe una clasificación registrada por
este correo para ese libro y concepto.

Interoperabilidad confirmada: un cliente de terceros (Zeep), que genera
su propio stub a partir del WSDL, consumió las 4 operaciones exitosamente.
```

Zeep, además, imprimió el contrato completo interpretado desde el WSDL
(operaciones, tipos, bindings) sin ningún ajuste manual — confirma que
el WSDL es válido y autocontenido como documento de contrato.

## 8. Verificación de persistencia en PostgreSQL

```sql
SELECT clasificacion_id, clasificador_id, book_id, concept_id, modelo_cloud,
       cliente_tipo, clasificado_en
FROM clasificaciones_cloud ORDER BY clasificacion_id;
```

Cada prueba de las secciones 3–7 generó una fila real (7 en total al
cierre de esta sesión), con `cliente_tipo` reflejando qué cliente la
originó (`plan-de-pruebas`, `escritorio-tkinter-prueba-real`,
`zeep-interoperabilidad`, `medicion-metricas`), y `clientes_servidos`
contabilizando correctamente las peticiones por tipo de cliente — tal
como exige la Parte 16 del enunciado.

## 9. Métricas reales (Tarea 5)

Ver `docs/METRICAS.md`.

## 11. Segunda ronda: migración a Stored Procedures y Vistas (ED-11)

Aplicada el mismo día contra la misma instancia (`sql/migracion_sp_vistas.sql`,
generado a partir del bloque nuevo de `sql/soap_module.sql`, aplicado sin
recrear las tablas ya existentes):

```
BEGIN
CREATE FUNCTION   -- fn_registrar_peticion_cliente (sin cambios funcionales)
CREATE VIEW       -- v_conceptos_clasificables
CREATE FUNCTION   -- fn_conceptos_pendientes
CREATE FUNCTION   -- fn_registrar_clasificacion
CREATE FUNCTION   -- fn_progreso_usuario
CREATE VIEW       -- v_estadisticas_por_modelo
REVOKE (x4)       -- retira el acceso directo a tablas de la versión anterior
GRANT (x4)        -- solo EXECUTE en las 3 funciones + SELECT en la vista
COMMIT
```

**Bug real encontrado y corregido durante esta migración**: la primera
versión de `db/repository.py` usaba
`psycopg2.errors.lookup("LC001")` a nivel de módulo para poder capturar
el SQLSTATE personalizado que `fn_registrar_clasificacion` lanza en el
caso "concepto inexistente". Al reiniciar el servicio, esto hizo que
**el proceso ni siquiera arrancara**: `psycopg2.errors.lookup()` solo
reconoce los SQLSTATE que psycopg2 ya trae incorporados (los del
estándar SQL y los reservados de PL/pgSQL) y lanza `KeyError` para
cualquier código custom, en vez de crear una clase dinámicamente como se
asumió al escribirlo. Corregido capturando `psycopg2.Error` genérico y
comparando `exc.pgcode` a mano en el cuerpo del `except` — ese atributo
sí refleja el SQLSTATE real enviado por el servidor, tenga o no psycopg2
una clase Python para él.

**Todas las pruebas se repitieron después del fix, contra el servicio ya
migrado:**

```
=== WS-Security ===
[PASS] WS01 credenciales correctas: HTTP 200
[PASS] WS02a password incorrecto: HTTP 401
[PASS] WS02b usuario inexistente: HTTP 401
[PASS] WS02c digest manipulado: HTTP 401
[PASS] WS03a sin soap:Header: HTTP 401
[PASS] WS03b nonce repetido (replay): HTTP 401

=== Cliente de escritorio real ===
Total conceptos: 66
Registro exitoso vía fn_registrar_clasificacion (clasificacion_id=8)
Duplicado detectado correctamente (unique_violation real)
Progreso calculado correctamente vía fn_progreso_usuario

=== Concepto inexistente / modelo inválido ===
[PASS] N02 concepto inexistente: codigo='ConceptoInexistente'
       mensaje='No existe el concepto 999999 para el libro 999999.'
[PASS] N03 modelo invalido: codigo='ModeloInvalido'
       mensaje="'XaaS' no es un modeloCloud válido (use IaaS, PaaS, SaaS o FaaS)."

=== Interoperabilidad (cliente Zeep) ===
Las 4 operaciones, incluido el Fault de duplicado, funcionaron sin cambios
en el cliente — confirma que la migración no rompió el contrato WSDL.
```

**Verificación directa del mínimo privilegio reforzado**, conectando como
`soap_service_user` (no como superusuario):

```
$ psql -U soap_service_user -d library_db -c 'SELECT * FROM clasificaciones_cloud LIMIT 1;'
ERROR:  permission denied for table clasificaciones_cloud

$ psql -U soap_service_user -d library_db -c 'SELECT * FROM fn_conceptos_pendientes() LIMIT 1;'
 book_id |     isbn      | titulo_libro | ... (fila real devuelta correctamente)
```

Confirma en la práctica lo que documenta ED-11: el rol de aplicación ya
no puede leer/escribir ninguna tabla directamente, solo invocar las
funciones y la vista que el contrato expone.

## 12. Qué falta de evidencia (por hacerse en la propia máquina/cuenta del usuario)

- Capturas de pantalla de la GUI de escritorio real (Tkinter no se puede
  operar sin interfaz gráfica desde esta sesión ni desde la instancia
  headless; se validó el mismo código Python que la GUI invoca, no la
  interacción visual).
- Publicación de la página de reporte técnico en `ubiquitous.udem.edu`.
- La instancia GCP se detiene al finalizar esta sesión de trabajo para
  no generar costo continuo — para repetir cualquier prueba, hay que
  volver a iniciarla (`gcloud compute instances start maquina-02 --zone=northamerica-south1-c`).
