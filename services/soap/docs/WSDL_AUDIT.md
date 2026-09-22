# Auditoría del contrato WSDL — Tarea 3

Recorre cada campo de cada una de las 4 operaciones de
`wsdl/library-classifier.wsdl`, dato por dato: origen real del dato (columna
del monolito o tabla propia), si se expone, qué transformación sufre y por
qué. Complementa —sin reemplazar— el resumen que ya existe en
`docs/CONTRATO_DISENO.md` §6, que cubre sólo los datos más sensibles a alto
nivel; esta tabla es exhaustiva, campo por campo, tal como pide la Tarea 3
del enunciado.

Convención de la columna "¿Se expone?": **Sí (salida)** = viaja en la
`Response` al cliente; **Entrada** = el cliente lo envía en el `Request`,
no es algo que el servidor "exponga" pero sí es dato que el servidor recibe
y debe tratar con cuidado; **No** = existe en el modelo de datos pero
deliberadamente nunca sale ni entra en esta operación.

## 1. ObtenerConceptosPendientes

### Request

| Dato | Operación | ¿Se expone? | Transformación | Justificación |
|---|---|---|---|---|
| `filtroCorreo` | ObtenerConceptosPendientes | Entrada (opcional) | Ninguna; se usa para hacer `JOIN` contra `clasificadores.correo` → `clasificaciones_cloud` y excluir lo ya clasificado | Permite personalizar la lista sin exigir autenticación; si se omite, devuelve el catálogo completo clasificable (comentario del propio WSDL: "útil para explorar antes de identificarse") |
| `filtroCategoria` | ObtenerConceptosPendientes | Entrada (opcional) | Ninguna; se compara contra `categories.name` | Acota resultados por categoría sin necesidad de que el cliente conozca `category_id` |

### Response (`ConceptoPendiente`, repetido)

| Dato | Columna/origen real | ¿Se expone? | Transformación | Justificación |
|---|---|---|---|---|
| `bookId` | `books.book_id` | Sí (salida) | Ninguna | Necesario como referencia para que `RegistrarClasificacion` sepa a qué libro asociar la clasificación |
| `isbn` | `books.isbn` | Sí (salida) | Ninguna | El clasificador necesita identificar el libro físico/editorial que está viendo |
| `tituloLibro` | `books.title` | Sí (salida) | Renombrado (`title` → `tituloLibro`, contrato en español) | Contexto legible para elegir el concepto correcto |
| `categoria` | `categories.name` (vía `books.category_id` → `categories.category_id`) | Sí (salida) | `JOIN`, sin transformar el valor | Contexto para elegir el concepto correcto |
| `conceptoId` | `concepts.concept_id` | Sí (salida) | Ninguna | Clave necesaria para `RegistrarClasificacion` |
| `concepto` | `concepts.name` | Sí (salida) | Renombrado (`name` → `concepto`) | Es literalmente lo que hay que clasificar |
| `definicion` | `book_concepts.definition` | Sí (salida) | Ninguna | La definición es contextual al par (libro, concepto) por diseño 4FN del monolito — puede diferir entre libros para el mismo concepto, y esa es justo la información que el clasificador necesita leer |
| `total` | Calculado (`COUNT`) | Sí (salida) | Agregación, no es columna real | Da contexto de tamaño del resultado al cliente |
| — | `books.price`, `books.stock` | **No** | — | Irrelevante para clasificar; dato comercial interno del monolito (ver también `CONTRATO_DISENO.md` §6) |
| — | `books.publication_year`, `books.format_id` | **No** | — | No aporta nada a la tarea de clasificación Cloud |
| — | `categories.category_id`, `categories.description` | **No** | — | Sólo se expone el nombre de la categoría, no su identificador interno ni su descripción larga |
| — | `book_concepts.created_at`/`updated_at` | **No** | — | Metadato de auditoría interno del monolito, no relevante para el clasificador |

## 2. RegistrarClasificacion

### Request

| Dato | Operación | ¿Se expone? | Transformación | Justificación |
|---|---|---|---|---|
| `nombre` | RegistrarClasificacion | Entrada | Se persiste en `clasificadores.nombre` sólo si el clasificador es nuevo (upsert por `correo`; si ya existe, no se sobrescribe con datos distintos — `CONTRATO_DISENO.md` §2, punto 2) | Identifica a la persona para reportes de progreso |
| `apellidos` | RegistrarClasificacion | Entrada | Igual que `nombre`, hacia `clasificadores.apellidos` | Igual |
| `correo` | RegistrarClasificacion | Entrada | Clave de upsert de `clasificadores`; validado con la misma regex que el `CHECK` de la tabla | Identificador de negocio del clasificador — ver riesgo **R-01** más abajo |
| `bookId` | RegistrarClasificacion | Entrada | Validado por existencia compuesta contra `book_concepts (book_id, concept_id)` antes de cualquier `INSERT` | De qué libro es la clasificación |
| `conceptoId` | RegistrarClasificacion | Entrada | Igual, parte de la misma validación compuesta | De qué concepto es la clasificación |
| `modeloCloud` | RegistrarClasificacion | Entrada | Validado contra la enumeración `IaaS/PaaS/SaaS/FaaS` antes de tocar la base de datos (`ModeloInvalido` (prefijo real en el código: `tns`, no `lib` — ver `docs/ENGINEERING_DECISIONS.md` ED-08) si falla) | El juicio de clasificación en sí — el propósito central de la operación |
| `tipoCliente` | RegistrarClasificacion | Entrada | Se persiste en `clasificaciones_cloud.cliente_tipo` y en `clientes_servidos.tipo_cliente`/`peticiones_atendidas` vía `fn_registrar_peticion_cliente` | Métrica de qué tipo de cliente SOAP hizo la petición (escritorio, interoperabilidad, etc.), sin identificar a la persona |
| — | `ip_origen` de `clasificaciones_cloud` | No es un campo del `Request` | Se llena del lado servidor a partir de la conexión HTTP entrante, **nunca** viene del Body SOAP | Evita que un cliente falsifique su propia IP de origen enviándola como dato |

### Response

| Dato | Columna/origen real | ¿Se expone? | Transformación | Justificación |
|---|---|---|---|---|
| `clasificacionId` | `clasificaciones_cloud.clasificacion_id` | Sí (salida) | Ninguna | Referencia/confirmación de la fila creada |
| `modeloCloud` | Eco del valor recibido | Sí (salida) | Ninguna | Confirma qué se registró |
| `clasificadoEn` | `clasificaciones_cloud.clasificado_en` | Sí (salida) | `timestamptz` → `xsd:dateTime` | Trazabilidad para quien clasificó |
| `mensaje` | Generado por el servidor, no es columna | Sí (salida) | Texto construido en `soap/service.py` | Confirmación legible para humanos |
| — | `clasificaciones_cloud.clasificador_id` | **No** | — | Identificador interno (PK de `clasificadores`); el cliente ya conoce su propio `correo`, no necesita el id numérico |
| — | `clasificaciones_cloud.ip_origen` | **No** | — | Dato de auditoría de servidor; no tiene utilidad para el cliente y podría filtrar información de red |
| — | `clientes_servidos.*` | **No** | — | Tabla de métricas agregadas por tipo de cliente, sin propósito en la respuesta de esta operación |

## 3. ObtenerProgresoUsuario

### Request

| Dato | Operación | ¿Se expone? | Transformación | Justificación |
|---|---|---|---|---|
| `correo` | ObtenerProgresoUsuario | Entrada (obligatorio) | Ninguna, salvo validación de formato | Identifica de quién se calcula el progreso — ver riesgo **R-01** |

### Response

| Dato | Origen real | ¿Se expone? | Transformación | Justificación |
|---|---|---|---|---|
| `correo` | Eco del valor recibido | Sí (salida) | Ninguna | Confirma sobre quién es el reporte |
| `totalConceptos` | `COUNT(*)` sobre todo `book_concepts` | Sí (salida) | Agregación | Denominador del progreso |
| `totalClasificados` | `COUNT(*)` sobre `clasificaciones_cloud` para el `clasificador_id` de ese correo | Sí (salida) | Agregación | Numerador del progreso |
| `totalPendientes` | Calculado (`totalConceptos − totalClasificados`) | Sí (salida) | Agregación derivada | Complemento útil para el cliente sin que tenga que restar |
| `porcentajeCompletado` | Calculado | Sí (salida) | Agregación derivada, `decimal` | Resumen de una cifra fácil de mostrar en la UI de escritorio |

Esta operación es, junto con `RegistrarClasificacion`, la más expuesta al
riesgo **R-01**: el único requisito para obtener el progreso de *cualquier*
correo es conocerlo o adivinarlo — no hay verificación de que quien
pregunta sea el dueño real de ese correo.

## 4. ObtenerEstadisticasPorModelo (protegida con WS-Security)

### Request (Body vacío + cabecera `soap:Header`)

| Dato | Dónde viaja | ¿Se expone? | Transformación | Justificación |
|---|---|---|---|---|
| — (Body) | `ObtenerEstadisticasPorModeloRequest` | — | `xsd:sequence` vacía | La operación no necesita parámetros de negocio; sólo credenciales |
| `wsse:Username` | `soap:Header` | Entrada | Se compara contra `soap_service_credenciales.usuario` | Identifica al cliente de reportes autorizado |
| `wsse:Password` (`Type=...PasswordDigest`) | `soap:Header` | Entrada, **nunca viaja en claro** | El servidor descifra `soap_service_credenciales.password_cifrada` (Fernet + `WSSE_MASTER_KEY`, fuera de la BD) para recuperar la contraseña real, recalcula `Base64(SHA1(nonce+created+password_real))` y compara — ver `docs/ENGINEERING_DECISIONS.md` ED-07 y `README.md` §3 ED-04 | Autenticación sin exponer el secreto por la red; el cifrado reversible con clave separada de la BD evita que una fuga de solo la base de datos baste para autenticarse — ver histórico en riesgo **R-05 (resuelto)** |
| `wsse:Nonce` | `soap:Header` | Entrada | Se usa una sola vez dentro de la ventana de tolerancia; se descarta/registra para detectar repetición | Mitiga *replay* de la misma petición capturada |
| `wsu:Created` | `soap:Header` | Entrada | Se valida contra `WSSE_NONCE_WINDOW_SECONDS` (tolerancia ~5 min) | Mitiga *replay* de peticiones viejas |

### Response

| Dato | Origen real | ¿Se expone? | Transformación | Justificación |
|---|---|---|---|---|
| `estadistica[].modeloCloud` | `clasificaciones_cloud.modelo_cloud` (agrupado) | Sí (salida) | `GROUP BY` | Dato agregado, no identifica a ninguna persona |
| `estadistica[].totalClasificaciones` | `COUNT(*) GROUP BY modelo_cloud` | Sí (salida) | Agregación | Métrica de negocio |
| `estadistica[].porcentaje` | Calculado | Sí (salida) | Agregación derivada | Facilita lectura sin que el cliente tenga que calcularlo |
| `totalGeneral` | `COUNT(*)` total | Sí (salida) | Agregación | Denominador para los porcentajes |
| — | `soap_service_credenciales.password_cifrada` / `WSSE_MASTER_KEY` | **No, nunca** | — | Ni en la respuesta ni en ningún `Fault`; el texto cifrado sólo vive en la tabla y la clave maestra sólo en el `.env` del servidor |
| — | `clasificaciones_cloud.clasificador_id`/`book_id`/`concept_id`/`ip_origen` a nivel de fila individual | **No** | — | La respuesta es 100% agregada; no lista clasificaciones individuales — es justamente lo que distingue a esta operación de un volcado de datos personales, y por qué sólo ella exige WS-Security en vez de las otras tres |

## 5. Riesgos identificados y mitigación propuesta

### R-01 — El `correo` es la única "identificación" en 3 de las 4 operaciones, sin verificar posesión

`RegistrarClasificacion`, `ObtenerProgresoUsuario` y el `filtroCorreo` de
`ObtenerConceptosPendientes` usan `correo` como identificador de negocio,
pero ninguna de las tres exige contraseña ni WS-Security (decisión
deliberada, ver `CONTRATO_DISENO.md` §2 y `docs/ENGINEERING_DECISIONS.md`
ED-05). Consecuencia real: cualquiera puede (a) consultar cuánto ha
clasificado un correo ajeno —fuga de información de uso— y (b) registrar
clasificaciones a nombre de un correo ajeno, "contaminando" o inflando el
historial de otra persona sin su consentimiento.

**Mitigación propuesta**: no se recomienda exigir contraseña aquí —
rompería el propósito pedagógico explícito de tener operaciones abiertas
para exploración sin fricción. En su lugar: (i) nunca agregar una
operación que liste todos los correos existentes (ya es así hoy — no hay
tal operación en el WSDL, y debe mantenerse así); (ii) usar
`clientes_servidos` (que ya registra peticiones por tipo de cliente) como
base para limitar la tasa de peticiones y detectar abuso; (iii) dejar
documentado —como aquí— que en un despliegue real (no académico) estas
tres operaciones deberían revisarse para exigir algún mecanismo de
verificación de posesión del correo (p. ej. un token de un solo uso
enviado por email), algo fuera del alcance de este ejercicio.

### R-02 — Acoplamiento por base de datos compartida entre el monolito y el módulo SOAP

Ambos procesos son independientes pero leen (y el módulo SOAP además
escribe en sus propias tablas) la misma `library_db`, sin ningún
mecanismo de coordinación de esquema entre ellos: no hay versión de
esquema, no hay vista de compatibilidad, no hay contrato explícito más
allá de "estas columnas de `books`/`categories`/`concepts`/
`book_concepts` existen con estos nombres". Ejemplo concreto: si
`integracion02` renombra `books.isbn` a `books.isbn_code` (una migración
perfectamente razonable desde el punto de vista del monolito, que no
tiene ninguna razón para saber que el módulo SOAP existe), cualquier
consulta de `soap/db.py` que referencie `isbn` falla en tiempo de
ejecución con un error de PostgreSQL (columna inexistente), que el
servicio traduce genéricamente a `soap:Server`/`ErrorInterno`
(`CONTRATO_DISENO.md` §4) — el cliente SOAP recibe un fault sin ninguna
pista real de la causa, y nadie se entera hasta que alguien prueba la
operación afectada.

**Mitigación propuesta**: (i) introducir una vista de sólo lectura (p.
ej. `v_conceptos_clasificables`) como el verdadero contrato de lectura
del módulo SOAP en vez de las tablas base — un cambio de nombre de
columna interno se absorbe actualizando la vista una sola vez, no cada
consulta dispersa en `soap/db.py`; (ii) documentar por escrito (en el
README de `integracion02` o en un acuerdo entre equipos) que
`books`/`categories`/`concepts`/`book_concepts` son superficie
compartida y cualquier cambio de nombre o tipo debe coordinarse antes de
aplicarse; (iii) una prueba de humo automatizada mínima que ambos
proyectos puedan correr después de cualquier cambio de esquema.

### R-03 — La validación de tipos XSD no está garantizada por `ElementTree`

El WSDL declara `modeloCloud` como un `xsd:simpleType` restringido a 4
valores, pero `xml.etree.ElementTree` (elegido en ED-06) sólo parsea XML
bien formado — no valida XSD. Si `soap/service.py` no reimplementa
explícitamente esa validación antes de tocar la base de datos (tal como
exige `CONTRATO_DISENO.md` §4, fila `ModeloInvalido`), el único control
real que queda es el `CHECK ck_clasificaciones_modelo_valido` de
PostgreSQL: un valor inválido llegaría hasta la base de datos y
produciría una excepción no capturada específicamente, cayendo en el
*fallback* `soap:Server`/`ErrorInterno` en vez del correcto
`ModeloInvalido` (prefijo real en el código: `tns`, no `lib` — ver `docs/ENGINEERING_DECISIONS.md` ED-08) (`soap:Client`) que el contrato promete — el cliente
sigue recibiendo un `Fault`, pero del tipo equivocado, y el log de
servidor registraría una excepción de integridad de base de datos como si
fuera una falla interna real.

**Mitigación propuesta**: validar explícitamente cada campo con
restricción de enumeración/formato en Python antes de cualquier SQL (ya
está prescrito en `CONTRATO_DISENO.md`; este riesgo es sobre la
disciplina de implementación, no sobre el contrato en sí); agregar una
prueba unitaria dedicada por cada fila de la tabla de faults de
`CONTRATO_DISENO.md` §4 una vez exista `soap/service.py`.

### R-04 — Identificadores internos secuenciales expuestos sin autenticación

`ObtenerConceptosPendientes` no requiere WS-Security y devuelve `bookId`/
`conceptoId` (claves primarias `bigint` autoincrementales de `books`/
`concepts`) a cualquier cliente que alcance el servicio en la red. A
diferencia del monolito, donde toda lectura del catálogo exige sesión
autenticada, aquí el catálogo completo de libros y conceptos es
enumerable sin ninguna barrera — un cliente automatizado podría
reconstruir todo `book_concepts` invocando la operación repetidamente
variando `filtroCategoria`. Es una decisión de diseño deliberada (el
propio WSDL documenta el caso de uso: "útil para explorar antes de
identificarse"), pero merece quedar registrada como riesgo aceptado
explícito, no como omisión.

**Mitigación propuesta**: limitar el tamaño de resultados por petición y
usar `clientes_servidos` para detectar volumen anómalo de peticiones por
cliente después del hecho; si el catálogo llegara a incluir en el futuro
datos más sensibles que definiciones de conceptos Cloud, esta operación
tendría que revisarse desde cero.

### R-05 (resuelto) — Una primera versión de WS-Security usaba el hash almacenado como secreto compartido equivalente ("pass the hash")

Hallazgo original sobre una primera implementación (`soap/security.py`):
el contrato exigía que el servidor nunca guardara la contraseña en claro
(sólo `SHA-256(sal+password)`), pero el perfil clásico de `PasswordDigest`
de WS-Security exige que el servidor recalcule
`SHA1(nonce+created+password)` — algo imposible si sólo tiene un hash de
un solo sentido. Esa primera versión usaba el propio `password_hash`
almacenado como el valor "password" dentro de la fórmula, lo que tenía
un efecto colateral real: el hash dejaba de ser sólo un dato de
almacenamiento interno y pasaba a ser, en sí mismo, el secreto que había
que proteger — igual que en un ataque "pass the hash" contra NTLM,
cualquiera que obtuviera ese hash podía autenticarse indefinidamente sin
necesitar la contraseña original, a diferencia de un hash real
(bcrypt/Argon2), donde poseerlo no basta para autenticarse sin además
romperlo.

**Corrección aplicada**: `soap_service_credenciales.password_cifrada`
guarda la contraseña **cifrada** (no hasheada) con Fernet
(`cryptography`, AES simétrico autenticado) usando una clave maestra
`WSSE_MASTER_KEY` que vive solo en la variable de entorno del servidor,
nunca en la base de datos. El servidor descifra para recuperar la
contraseña real y calcula el digest clásico correctamente con ella. Esto
sí resuelve el conflicto de raíz: una fuga de solo la base de datos ya
no basta para autenticarse (hace falta también la clave maestra del
servidor, que vive fuera de la BD), y el perfil PasswordDigest queda
implementado según su definición real, no adaptado. Ver
`docs/ENGINEERING_DECISIONS.md` ED-07 y `README.md` §3 ED-04 para el
detalle completo, incluida la versión anterior descartada.

## 6. Conclusión: contrato estricto vs. mantenibilidad

El WSDL/XSD de este servicio es deliberadamente estricto: tipos cerrados
(`ModeloCloud` como enumeración, no `xsd:string` libre), mensajes
tipados por operación, y un catálogo cerrado de `Fault` con código propio
por caso. Esa rigidez es la que le da valor real a la interoperabilidad
(ED-09): cualquier cliente que genere su stub desde este WSDL obtiene
garantías fuertes sobre qué puede enviar y qué puede esperar recibir, sin
necesidad de leer el código Python del servidor.

El costo de esa rigidez es que el módulo SOAP queda acoplado a la forma
exacta de tablas que no le pertenecen (R-02): un contrato estricto en el
borde (el WSDL hacia el cliente) no protege automáticamente el interior
(las consultas SQL hacia el monolito). La solución razonable no es
relajar el WSDL —eso anularía la razón misma por la que se eligió SOAP
sobre REST/GraphQL (ED-02, ED-03)— sino introducir una capa de
indirección interna (vistas de sólo lectura, como propone R-02) que
absorba los cambios del esquema físico sin que el contrato público hacia
el cliente tenga que moverse. En otras palabras: el contrato con el
mundo exterior debe seguir siendo estricto y estable; lo que necesita
flexibilidad para poder mantenerse a lo largo del tiempo es la capa
intermedia entre ese contrato y el esquema físico compartido, que hoy no
existe y queda documentada aquí como trabajo pendiente razonable, no
como parte del alcance mínimo de este ejercicio.
