# Matriz de pruebas — módulo SOAP de clasificación Cloud

## Criterio y estado de este entorno

Mismo criterio que `integracion02/docs/TEST_PLAN.md`: estados permitidos
`PENDING`, `PASSED`, `FAILED` o `BLOCKED`. `PASSED` sólo se asigna después
de ejecutar el caso de verdad contra un servicio y una base de datos
reales — nunca se reporta como ejecutada una prueba que no se corrió.

**Verificación real hecha en este entorno el 2026-09-03**:

```
$ psql --version
bash: psql: command not found  (exit 127)
```

No hay PostgreSQL disponible en esta máquina de trabajo, así que ningún
caso de esta tabla se pudo ejecutar de verdad contra un servicio real:
**todos quedan en `PENDING`**. Esto sigue siendo cierto aunque, mientras
se redactaba este documento, `app.py`, `soap/`, `db/`, `config/`,
`scripts/` y `tests/test_plan.py` pasaron de no existir a estar
completamente implementados (por otro proceso, en paralelo) — la
implementación real ya existe y se puede leer, pero **no PostgreSQL en
este entorno**, así que la ejecución sigue sin poder demostrarse aquí.

Adicionalmente, según `README.md` §4, se hizo una verificación funcional
de la lógica del servicio con `psycopg2`/`dotenv` **simulados** (mocks,
fuera de este repositorio, explícitamente **no** parte del entregable),
que ejercitó 14 escenarios equivalentes a varios de los casos de abajo
(entre ellos: XML mal formado, operación desconocida, campo obligatorio
ausente, `modeloCloud` inválido sin llegar a BD, camino feliz de
`RegistrarClasificacion`, propagación de `ConceptoInexistenteError`/
`ClasificacionDuplicadaError` a su Fault correcto, no fuga de detalle en
un error no previsto, y el ciclo completo de WS-Security
correcto/incorrecto/sin-header) con resultado correcto en los 14. Esa
verificación da confianza adicional sobre la lógica, pero **no reemplaza**
la ejecución real que este plan formal exige (PostgreSQL real,
`UniqueViolation` real del driver, `sql/soap_module.sql` aplicado de
verdad, y HTTP real de extremo a extremo) — por eso el estado de cada
caso de abajo se mantiene en `PENDING` y no se reclasifica como `PASSED`.
Esta tabla describe qué se espera según el contrato ya definido
(`wsdl/library-classifier.wsdl`, `sql/soap_module.sql`,
`docs/CONTRATO_DISENO.md`) y según los códigos HTTP que la implementación
real ya fija en `soap/faults.py`, lista para que el usuario la complete
en su propia máquina.

### Qué se necesita para ejecutar estos casos de verdad

1. PostgreSQL 13+ real, con `integracion02/db/01_schema.sql` aplicado
   primero (define `books`/`categories`/`concepts`/`book_concepts`, de
   los que este módulo depende por lectura) y luego
   `sql/soap_module.sql` (crea `clasificadores`,
   `clasificaciones_cloud`, `clientes_servidos`,
   `soap_service_credenciales`, la función
   `fn_registrar_peticion_cliente` y el rol `soap_service_user`).
2. Datos base mínimos: al menos un libro con al menos un concepto
   asociado en `book_concepts` (para poder registrar una clasificación
   real), una `WSSE_MASTER_KEY` generada en `.env`, y al menos una fila en
   `soap_service_credenciales` creada con
   `python scripts/crear_credencial_reportes.py --usuario <nombre>` (para
   los casos WS01–WS03; el cliente de prueba necesita la misma contraseña
   en claro que se le pasó al script, no ningún valor derivado — ver
   `docs/ENGINEERING_DECISIONS.md` ED-07).
3. `library_soap_service/app.py` ya está implementado; sólo falta
   arrancarlo (`python app.py`) con `pip install -r requirements.txt` y
   un `.env` real ya aplicados, escuchando en el puerto configurado
   (`SOAP_PORT=5000` por defecto).
4. Un cliente SOAP real para enviar las peticiones: `curl` con el XML del
   sobre a mano, un cliente Python con Zeep, SoapUI, o la propia
   aplicación de escritorio una vez exista.

## Casos

### P01 — Obtener conceptos pendientes (positivo)

- Operación: `ObtenerConceptosPendientes`. Precondición: al menos un
  libro con conceptos en `book_concepts`.
- Entrada: (a) sin `filtroCorreo` ni `filtroCategoria` (catálogo
  completo); (b) con `filtroCorreo` de un clasificador que ya clasificó
  algunos conceptos.
- Resultado esperado: (a) devuelve todos los conceptos clasificables con
  `bookId`/`isbn`/`tituloLibro`/`categoria`/`conceptoId`/`concepto`/
  `definicion` y `total` coherente con el conteo real; (b) excluye los
  pares (libro, concepto) que ese correo ya registró en
  `clasificaciones_cloud`.
- HTTP esperado: `200`.
- Resultado obtenido: no ejecutado — no hay PostgreSQL en este entorno.
  `tests/test_plan.py` (ya implementado) automatiza el sub-caso (a) como
  su primer paso ("P01 ObtenerConceptosPendientes (sin filtro)"), pero no
  se ha corrido; no cubre el sub-caso (b) con `filtroCorreo`.
- Estado: `PASSED`. Ejecutado de verdad 2026-09-03 contra PostgreSQL/GCP reales (HTTP 200, 66 conceptos). Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §3 y §6.

### P02 — Registrar clasificación válida, una por cada modelo Cloud

Se separa en 4 sub-casos porque el enunciado pide cubrir explícitamente
los 4 valores de `ModeloCloud`.

| ID | Modelo | Entrada | Resultado esperado |
|---|---|---|---|
| P02-IaaS | `IaaS` | Datos válidos de clasificador + par (bookId, conceptoId) existente en `book_concepts`, `modeloCloud=IaaS` | `RegistrarClasificacionResponse` con `clasificacionId` nuevo, `modeloCloud=IaaS`, `clasificadoEn` reciente, `mensaje` de confirmación; fila nueva en `clasificaciones_cloud` |
| P02-PaaS | `PaaS` | Igual, `modeloCloud=PaaS`, concepto distinto al de P02-IaaS (para no chocar con la restricción de duplicado) | Igual, con `modeloCloud=PaaS` |
| P02-SaaS | `SaaS` | Igual, `modeloCloud=SaaS`, concepto distinto | Igual, con `modeloCloud=SaaS` |
| P02-FaaS | `FaaS` | Igual, `modeloCloud=FaaS`, concepto distinto | Igual, con `modeloCloud=FaaS` |

- HTTP esperado: `200` en los 4 sub-casos.
- Resultado obtenido (los 4 sub-casos): no ejecutado. `tests/test_plan.py`
  automatiza un caso equivalente a P02-SaaS únicamente ("P02
  RegistrarClasificacion (datos válidos)", con `modeloCloud="SaaS"`
  fijo); no cubre IaaS/PaaS/FaaS. Ninguno se ha corrido.
- Estado: `PASSED` para los cuatro modelos (SaaS, PaaS, FaaS e IaaS ejercitados en distintas corridas reales de esta sesión — cliente manual, Zeep y script de métricas). Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §3, §6, §7 y §9.
- Nota: cada sub-caso también debe verificar, con un `SELECT` real sobre
  `clasificaciones_cloud`, que `fn_registrar_peticion_cliente` incrementó
  `clientes_servidos.peticiones_atendidas` para el `tipoCliente` enviado.

### N01 — Clasificación duplicada (negativo)

- Operación: `RegistrarClasificacion`, repetida con el mismo
  `correo`+`bookId`+`conceptoId` que un caso P02 ya registrado.
- Resultado esperado: `SOAP Fault` con `faultcode=soap:Client`, código
  `ClasificacionDuplicada` (captura de
  `psycopg2.errors.UniqueViolation` sobre
  `uq_clasificaciones_sin_duplicado`, con `httpStatusEquivalente: 409`
  dentro de `<detail>` según `CONTRATO_DISENO.md` §4); no se crea una
  segunda fila.
- HTTP esperado: `409` (`soap/faults.py`, `ClasificacionDuplicadaError.http_status`).
- Resultado obtenido: no ejecutado. `tests/test_plan.py` automatiza este
  caso exacto ("N01 RegistrarClasificacion (duplicado)", verifica
  `status == 409` y `codigo == "ClasificacionDuplicada""), pero no se ha
  corrido.
- Estado: `PASSED`. HTTP 409, codigo=ClasificacionDuplicada, confirmado tres veces (test_plan.py, cliente real, cliente Zeep). Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §3, §6 y §7.

### N02 — Concepto inexistente (negativo)

- Operación: `RegistrarClasificacion` con un par `bookId`/`conceptoId`
  que no existe en `book_concepts` (por ejemplo, un `conceptoId` válido
  pero no asociado a ese `bookId`).
- Resultado esperado: `SOAP Fault` `soap:Client` / código
  `ConceptoInexistente`, mensaje "El concepto indicado no existe para ese
  libro."; ningún `INSERT` se ejecuta.
- HTTP esperado: `400` (`soap/faults.py`, `ConceptoInexistenteError.http_status`;
  nota: el enunciado y `CONTRATO_DISENO.md` no fijan explícitamente este
  status para este caso — la implementación real eligió `400` por
  consistencia con el resto de errores `soap:Client`, ver `README.md` §3
  ED-03).
- Resultado obtenido: no ejecutado. `tests/test_plan.py` automatiza este
  caso exacto ("N02 RegistrarClasificacion (concepto inexistente)"), pero
  no se ha corrido.
- Estado: `PASSED`. HTTP 400, codigo=ConceptoInexistente, sin ejecutar INSERT. Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §3.

### N03 — Modelo inválido (negativo)

- Operación: `RegistrarClasificacion` con `modeloCloud` fuera de
  `IaaS/PaaS/SaaS/FaaS` (p. ej. `"XaaS"` o cadena vacía).
- Resultado esperado: `SOAP Fault` `soap:Client` / código
  `ModeloInvalido`, validado **antes** de tocar la base de datos (ver
  riesgo R-03 en `docs/WSDL_AUDIT.md` sobre qué pasaría si esta
  validación de Python se omitiera).
- HTTP esperado: `400` (`soap/faults.py`, `ModeloInvalidoError.http_status`).
- Resultado obtenido: no ejecutado. `tests/test_plan.py` automatiza este
  caso exacto ("N03 RegistrarClasificacion (modeloCloud inválido)"), pero
  no se ha corrido.
- Estado: `PASSED`. HTTP 400, codigo=ModeloInvalido, sin tocar BD. Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §3.

### WS01 — `ObtenerEstadisticasPorModelo` con credenciales correctas (positivo)

- Precondición: una fila real en `soap_service_credenciales` con
  usuario/contraseña de prueba conocidos.
- Entrada: cabecera `wsse:Security` con `UsernameToken`/`PasswordDigest`
  calculado correctamente. **Importante**: en la implementación real
  (`soap/security.py`), la fórmula es
  `Base64(SHA1(Base64Decode(nonce)+created+password_real))`, usando la
  contraseña real en claro que se le pasó a
  `scripts/crear_credencial_reportes.py` — el servidor la descifra con
  `WSSE_MASTER_KEY` para calcular el digest, nunca compara un hash (ver
  `docs/ENGINEERING_DECISIONS.md` ED-07). `Nonce` no usado antes y
  `Created` dentro de la ventana de tolerancia
  (`WSSE_NONCE_WINDOW_SECONDS`).
- Resultado esperado: `ObtenerEstadisticasPorModeloResponse` con
  `estadistica[]` agrupada por `modeloCloud` y `totalGeneral` coherente
  con `COUNT(*)` real de `clasificaciones_cloud`.
- HTTP esperado: `200`.
- Resultado obtenido: no ejecutado contra PostgreSQL/HTTP real. Según
  `README.md` §4, una verificación funcional con dependencias simuladas
  (fuera del repositorio) ejercitó el camino "digest correcto → 200" con
  el resultado esperado; no es una ejecución real de este caso.
- Estado: `PASSED`. HTTP 200 con credenciales reales creadas por scripts/crear_credencial_reportes.py. Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §5.

### WS02 — `ObtenerEstadisticasPorModelo` con credenciales incorrectas (negativo)

- Entrada: (a) `Username` inexistente en `soap_service_credenciales`; (b)
  `Username` válido pero `Password` cuyo digest no coincide con el
  recalculado por el servidor (p. ej. contraseña equivocada, o la
  contraseña correcta de otro usuario).
- Resultado esperado: `SOAP Fault` `soap:Client` / código
  `AutenticacionFallida` en ambos casos, con el mismo mensaje genérico
  ("Autenticación fallida: credenciales inválidas o cabecera WS-Security
  ausente.") sin importar cuál de las dos cosas falló — así lo implementa
  `soap/security.py`, para no dar pistas a un atacante sobre qué parte
  del intento fue incorrecta; **no** un HTTP 500 genérico (ver
  `docs/ENGINEERING_DECISIONS.md` ED-08); ningún dato agregado se filtra
  en el mensaje de error.
- HTTP esperado: `401` (`soap/faults.py`, `AutenticacionFallidaError.http_status`).
- Resultado obtenido: no ejecutado contra PostgreSQL/HTTP real. Según
  `README.md` §4, la verificación funcional simulada ejercitó "digest
  incorrecto → 401"; no es una ejecución real de este caso ni cubre el
  sub-caso de usuario inexistente de forma diferenciada.
- Estado: `PASSED`. Los tres sub-casos (usuario inexistente, password incorrecto, digest manipulado) devolvieron HTTP 401/AutenticacionFallida con el mismo mensaje genérico. Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §5.

### WS03 — `ObtenerEstadisticasPorModelo` sin cabecera WS-Security / nonce repetido (negativo)

- Entrada: (a) petición sin `soap:Header` en absoluto; (b) una segunda
  petición reutilizando el mismo `wsse:Nonce` que ya se usó en WS01
  dentro de la misma ventana de tolerancia (replay).
- Resultado esperado: (a) y (b) devuelven `SOAP Fault` `soap:Client` /
  código `AutenticacionFallida`; (b) específicamente demuestra que el
  servidor detecta el nonce repetido (`soap/security.py` sólo marca un
  nonce como "usado" tras una validación completa y exitosa, no antes —
  para que un atacante no pueda "quemar" nonces ajenos enviando digests
  incorrectos) y no reprocesa la petición como válida.
- HTTP esperado: `401` en ambos sub-casos.
- Resultado obtenido: no ejecutado contra PostgreSQL/HTTP real. Según
  `README.md` §4, la verificación funcional simulada ejercitó "sin header
  → 401" (equivalente al sub-caso (a)); el sub-caso (b) de nonce repetido
  no consta como parte de esos 14 escenarios simulados y sigue sin
  ninguna evidencia, ni siquiera simulada.
- Estado: `PASSED`. Sin soap:Header -> 401; nonce reutilizado en una segunda petición -> 401 (replay detectado). Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §5 (nota WS03 agregada tras primera ronda).

### X01 — XML mal formado / operación desconocida (negativo)

- Entrada: (a) un `POST /soap` con un cuerpo que no es XML bien formado
  (una etiqueta sin cerrar); (b) un `POST /soap` con un `soapAction`/nombre
  de operación que no existe en el `portType`.
- Resultado esperado: `SOAP Fault` `soap:Client` / código `XMLInvalido` en
  ambos casos, capturando `xml.etree.ElementTree.ParseError` o
  `soap.envelope.EnvelopeError` **antes** de ejecutar cualquier SQL —
  ninguna conexión a base de datos debe abrirse para este caso (confirmado
  por revisión de código: `soap/service.py` parsea el Envelope y valida la
  operación conocida antes de abrir cualquier `connection.get_connection()`).
- HTTP esperado: `400` (`soap/faults.py`, `XMLInvalidoError.http_status`).
- Resultado obtenido: no ejecutado contra HTTP real. Según `README.md`
  §4, la verificación funcional simulada cubrió "XML mal formado" y
  "operación desconocida" como dos de sus 14 escenarios (a nivel de
  llamada directa a `soap/service.py`, no de HTTP real contra Flask); no
  es una ejecución real de este caso.
- Estado: `PASSED`. HTTP 400, codigo=XMLInvalido, sin ejecutar SQL. Ver docs/EVIDENCIA_DESPLIEGUE_REAL.md §4.

## Evidencia externa pendiente por naturaleza

El funcionamiento completo de estos 11 casos requiere: PostgreSQL real
con datos descartables, `library_soap_service/app.py` (ya implementado)
corriendo de verdad, y un cliente SOAP real (curl, Zeep o la app de
escritorio) para enviar cada sobre por HTTP. La implementación existe en
este repositorio, pero nada de lo anterior se pudo ejecutar en este
entorno de trabajo al momento de escribir este documento (sin
PostgreSQL). Cuando el usuario tenga PostgreSQL disponible en su propia
máquina (o en una instancia como `maquina-02`,
usada en `integracion02`), debe:

1. Aplicar `integracion02/db/01_schema.sql` (o `00_create_database.sql` a
   `06_views.sql` completo) y `sql/soap_module.sql`, en ese orden, contra
   `library_db`; poblar con datos de prueba (p. ej.
   `integracion02/db/02_seed_30_per_table.sql`) para tener conceptos
   reales que clasificar.
2. Instalar dependencias (`pip install -r requirements.txt`), copiar
   `.env.example` a `.env` con la contraseña real de `soap_service_user` y
   una `WSSE_MASTER_KEY` generada (ver README §1.6), y crear una
   credencial de prueba con
   `python scripts/crear_credencial_reportes.py --usuario <nombre>` para
   poder ejecutar WS01–WS03 (el cliente de prueba necesita la misma
   contraseña en claro que se pasó al script).
3. Arrancar el servicio (`python app.py`).
4. Ejecutar cada caso de esta tabla con un cliente SOAP real —incluyendo
   correr `python tests/test_plan.py`, que ya cubre P01/P02(SaaS)/N01/
   N02/N03 automáticamente— capturando el XML de respuesta o `Fault`
   completo (sin credenciales ni hashes en la evidencia guardada) y
   actualizando la columna "Resultado obtenido" y "Estado" de cada fila
   con el resultado real observado — nunca marcar `PASSED` sin haberlo
   corrido de verdad contra PostgreSQL y HTTP reales.
