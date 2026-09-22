# Registro de decisiones de ingeniería — módulo SOAP de clasificación Cloud

Mismo esquema que `integracion02/docs/ENGINEERING_DECISIONS.md`, aplicado a
este módulo: **Necesidad/problema → alternativas consideradas → decisión
tomada → justificación técnica → riesgo o limitación → evidencia de
validación.**

Numeración propia (ED-01…) porque este es un proyecto distinto
(`library_soap_service/`), aunque comparte base de datos con
`integracion02`. Fuente de verdad de las decisiones ya tomadas:
`wsdl/library-classifier.wsdl`, `sql/soap_module.sql` y
`docs/CONTRATO_DISENO.md` — este documento las explica y las justifica, no
las redefine.

Este archivo cubre decisiones de **alto nivel** (qué stack, qué estilo de
contrato, qué perfil de seguridad, etc.). Las decisiones puntuales de
**implementación** que sólo tienen sentido una vez escrito el código
(estrategia de conexión a BD por request, el prefijo XML usado en el
`Fault`, el mapeo exacto de cada código de Fault a un status HTTP, y la
adaptación del digest de WS-Security para trabajar sólo con el hash
almacenado) están documentadas con su propia numeración ED-01…ED-06 en
`README.md` §3, para no duplicar contenido con números en conflicto entre
los dos archivos — cada decisión vive en un solo lugar.

**Estado de la implementación al momento de escribir esto**: `app.py`,
`soap/`, `db/`, `config/`, `scripts/` y `tests/test_plan.py` ya están
escritos (fueron implementados por otro proceso mientras se redactaba
este documento). El código se pudo revisar para verificar que las
decisiones de abajo efectivamente se siguieron; lo que sigue sin poder
verificarse en este entorno es su **ejecución contra PostgreSQL real**
(no hay `psql` disponible aquí — ver `docs/TEST_PLAN.md` y `README.md`
§4). Donde una decisión depende de esa evidencia, se dice explícitamente
que queda pendiente.

## ED-01. Flask/Python como stack del servicio SOAP

- **Necesidad/problema**: implementar el módulo SOAP como un proceso
  independiente del monolito Node.js (`integracion02/apps/web-monolito`),
  sin modificarlo, que hable SOAP 1.1 sobre HTTP y comparta la misma
  `library_db`.
- **Alternativas consideradas**: (a) Python + Flask; (b) Node.js/Express
  (mismo stack que el monolito, como un segundo proceso independiente);
  (c) Java con un framework SOAP nativo (Spring-WS, Apache CXF).
- **Decisión tomada**: (a) Flask.
- **Justificación técnica**: el enunciado del ejercicio pide explícitamente
  un módulo Flask/Python separado, precisamente para demostrar
  interoperabilidad real entre stacks distintos: el monolito ya es
  Node.js, así que un segundo servicio en el mismo lenguaje habría diluido
  esa demostración. `psycopg2` da acceso maduro y directo a PostgreSQL sin
  depender de un ORM, igual de robusto que `pg` del lado Node.
- **Riesgo o limitación**: dos runtimes distintos (Node y Python) en la
  misma máquina de desarrollo/despliegue duplican dependencias de sistema
  (dos gestores de paquetes, dos entornos virtuales) y exigen documentar
  dos procedimientos de arranque independientes en vez de uno.
- **Evidencia de validación**: `requirements.txt` (`flask`,
  `psycopg2-binary`, `python-dotenv`) y `.env.example` ya reflejan esta
  elección. `app.py` ya está escrito (Flask real, `GET /wsdl` y
  `POST /soap`); `python -m py_compile` sobre los `.py` del proyecto no
  encontró errores de sintaxis (ver `README.md` §4). La ejecución real del
  servicio contra PostgreSQL sigue pendiente en este entorno, que no tiene
  `psql` disponible (ver `docs/TEST_PLAN.md`).

## ED-02. SOAP frente a REST/GraphQL para este ejercicio

- **Necesidad/problema**: elegir el estilo de contrato de integración
  entre el cliente de escritorio, el módulo y (para la Tarea 4) un
  consumidor de interoperabilidad externo.
- **Alternativas consideradas**: (a) SOAP 1.1 document/literal con WSDL;
  (b) REST/JSON; (c) GraphQL.
- **Decisión tomada**: (a).
- **Justificación técnica**: SOAP es el objeto de estudio explícito de
  este ejercicio (contrato XML tipado con XSD, `SOAP Fault` estructurado,
  cabecera WS-Security, generación de clientes desde un WSDL). REST o
  GraphQL no habrían ejercitado ninguno de esos puntos, que son
  precisamente los que piden evaluar la Tarea 1 (WS-Security) y la Tarea 3
  (auditoría de contrato).
- **Riesgo o limitación**: SOAP es más verboso que REST/JSON y exige que
  cada cliente entienda XML y namespaces; para un caso de uso real de este
  tamaño, REST habría sido operacionalmente más simple de consumir. Se
  acepta el costo porque el objetivo es pedagógico, no de producción.
- **Evidencia de validación**: `wsdl/library-classifier.wsdl` define las 4
  operaciones exactamente en ese estilo (`document/literal`, SOAP 1.1
  sobre HTTP); ese mismo archivo es la fuente de verdad que la
  implementación (`soap/service.py`, ya escrita) debe cumplir — y, por
  revisión de código, su diccionario `OPERATIONS` cubre exactamente esas
  4 operaciones y ninguna más.

## ED-03. WSDL/XSD contract-first

- **Necesidad/problema**: decidir si el contrato XML se escribe antes de
  programar el servicio o se deriva después del código.
- **Alternativas consideradas**: (a) contract-first — escribir el
  WSDL/XSD a mano primero y hacer que el servicio lo cumpla; (b)
  code-first — escribir las funciones Python primero y generar el WSDL
  con una librería (p. ej. Spyne).
- **Decisión tomada**: (a).
- **Justificación técnica**: contract-first obliga a decidir
  explícitamente qué tipos y validaciones expone el servicio (p. ej.
  `ModeloCloud` como enumeración cerrada a IaaS/PaaS/SaaS/FaaS) antes de
  escribir una sola línea de acceso a datos, lo que facilita auditar la
  exposición de datos (Tarea 3, ver `docs/WSDL_AUDIT.md`) contra un
  documento fijo en vez de contra el comportamiento cambiante del código.
  También permite que el cliente de escritorio y cualquier consumidor de
  interoperabilidad empiecen a generar su stub desde el WSDL sin esperar
  a que el servidor exista.
- **Riesgo o limitación**: si la implementación real (`soap/service.py`)
  llegara a divergir del WSDL con el tiempo, el contrato quedaría
  desactualizado de forma silenciosa a menos que alguien lo revise
  manualmente; no hay una prueba automática de conformidad WSDL↔código
  planeada para este ejercicio.
- **Evidencia de validación**: el propio encabezado de
  `wsdl/library-classifier.wsdl` lo declara: "Documento primero,
  implementación después... `soap/service.py` debe implementar
  exactamente esto, no al revés." `soap/service.py` ya existe y su
  diccionario `OPERATIONS` despacha exactamente los 4 nombres de elemento
  raíz que define el WSDL (`ObtenerConceptosPendientesRequest`,
  `RegistrarClasificacionRequest`, `ObtenerProgresoUsuarioRequest`,
  `ObtenerEstadisticasPorModeloRequest`), confirmado por revisión de
  código; no hay todavía una prueba automática de conformidad WSDL↔código
  que lo verifique de forma continua.

## ED-04. Acceso a PostgreSQL vía `psycopg2` con SQL parametrizado

- **Necesidad/problema**: acceder a PostgreSQL desde Flask de forma
  segura y auditable, con el mismo criterio que ya usa el monolito con
  `pg` (`integracion02`, ED-02).
- **Alternativas consideradas**: (a) `psycopg2` con SQL parametrizado
  explícito (`%s`, nunca f-string/concatenación); (b) un ORM
  (SQLAlchemy); (c) un query builder.
- **Decisión tomada**: (a).
- **Justificación técnica**: mismo razonamiento que ED-02 de
  `integracion02`: un ORM añade una capa de abstracción no requerida para
  4 operaciones acotadas y dificulta demostrar de forma explícita que
  cada consulta está parametrizada; mantiene además consistencia de estilo
  con el resto del curso.
- **Riesgo o limitación**: sin ORM, la disciplina de nunca concatenar SQL
  recae por completo en cada función de acceso a datos (`soap/db.py`, aún
  no implementado); un descuido puntual sería una inyección SQL real, no
  sólo teórica, dado que varios campos de entrada (`correo`, `nombre`,
  `tipoCliente`) llegan directo del Body SOAP sin pasar antes por ningún
  framework que los sanee.
- **Evidencia de validación**: `sql/soap_module.sql` y
  `docs/CONTRATO_DISENO.md` §3 ya fijan esta decisión ("Todas las
  consultas parametrizadas (`%s`, nunca f-string/concat)"). `db/repository.py`
  ya está escrito y, revisado a mano, usa `%s`/`%(nombre)s` con
  `cur.execute(sql, params)` en las cinco funciones (una por operación
  más `obtener_credencial`); no se encontró ninguna consulta construida
  por concatenación o f-string con datos de entrada. La validación de
  ejecución real contra PostgreSQL sigue pendiente: este entorno no tiene
  `psql` disponible (`psql --version` → *command not found*, verificado
  el 2026-09-03). Ver `docs/TEST_PLAN.md`.

## ED-05. Tablas propias (`clasificadores`) en vez de reutilizar `users` del monolito

- **Necesidad/problema**: identificar a la persona que clasifica un
  concepto sin acoplar el módulo SOAP a la tabla de autenticación web
  administrativa del monolito.
- **Alternativas consideradas**: (a) reutilizar `users` (login
  administrativo de `integracion02`, con `password_hash`, `is_admin`);
  (b) tabla propia `clasificadores`, sin contraseña, identificada por
  correo único.
- **Decisión tomada**: (b).
- **Justificación técnica**: `users` es un dato de otro dueño
  (`apps/web-monolito`) con un propósito distinto (login administrativo
  con roles, protegido por bcrypt y la regla de "máximo un
  Administrador"); el módulo SOAP nunca debe escribir en tablas ajenas
  (ver `sql/soap_module.sql`: `soap_service_user` sólo tiene `SELECT` en
  `books/categories/concepts/book_concepts`, cero privilegios sobre
  `users`). Además, un clasificador de este ejercicio no necesita —ni
  debería tener— una contraseña de acceso al sistema administrativo del
  monolito.
- **Riesgo o limitación**: como `clasificadores` no tiene contraseña, el
  `correo` es efectivamente el único "identificador" en tres de las
  cuatro operaciones, lo cual es un riesgo real de suplantación de
  identidad ligera, documentado y aceptado deliberadamente (ver
  `docs/WSDL_AUDIT.md`, riesgo R-01).
- **Evidencia de validación**: `sql/soap_module.sql` (tabla
  `clasificadores`; `GRANT SELECT ON books, categories, concepts,
  book_concepts` —nunca `users`— a `soap_service_user`); nota final del
  mismo archivo: "NO tiene ningún privilegio sobre users/authors/formats/
  genres/book_authors/book_genres/book_images".

## ED-06. Construcción manual del XML con `ElementTree` (vs Spyne/Zeep en el servidor)

- **Necesidad/problema**: construir y parsear los sobres SOAP (Envelope,
  Header, Body, Fault) del lado servidor.
- **Alternativas consideradas**: (a) `xml.etree.ElementTree` de la
  librería estándar, construyendo el XML a mano; (b) un framework SOAP de
  servidor como Spyne; (c) usar Zeep también del lado servidor (no sólo
  del lado cliente).
- **Decisión tomada**: (a).
- **Justificación técnica**: `docs/CONTRATO_DISENO.md` §7 exige
  explícitamente `ElementTree` en el servidor —Zeep queda reservado para
  el cliente de interoperabilidad de la Tarea 4, es decir, un consumidor
  externo, no el servicio— para que el ejercicio demuestre entender la
  estructura real de un sobre SOAP (namespaces, `Header`/`Body`, `Fault`)
  en vez de delegarla por completo a una librería de alto nivel que la
  oculte.
- **Riesgo o limitación**: sin un framework, hay que reimplementar a mano
  la validación de tipos XSD (p. ej. que `modeloCloud` sea una de las 4
  enumeradas — ver riesgo R-03 en `docs/WSDL_AUDIT.md`) y el árbol de
  namespaces de WS-Security; un descuido en el escapado manual de XML
  podría reintroducir el riesgo que la regla `ET.SubElement(...).text =
  valor` (que sí escapa automáticamente) está pensada para evitar.
- **Evidencia de validación**: `docs/CONTRATO_DISENO.md` §7 fija esta
  regla explícitamente. `soap/envelope.py` ya la implementa: su función
  `set_text()` es, según su propio docstring, "la única forma en que este
  proyecto escribe datos de usuario dentro de un elemento XML"
  (`Element.text = value`, que `ElementTree` escapa automáticamente);
  revisado a mano, ni `soap/service.py` ni `soap/faults.py` construyen
  XML por concatenación de strings con datos de entrada. Ejecución real
  contra un cliente SOAP real sigue pendiente (ver `docs/TEST_PLAN.md`).

## ED-07. Perfil WS-Security elegido: `UsernameToken`/`PasswordDigest` (vs API key vs OAuth)

- **Necesidad/problema**: proteger `ObtenerEstadisticasPorModelo`, la
  única operación que expone un dato agregado de negocio y no un dato de
  catálogo público como las otras tres.
- **Alternativas consideradas**: (a) una API key simple en una cabecera
  HTTP custom; (b) WS-Security `UsernameToken` con `PasswordDigest`
  (perfil clásico de WS-Security 1.0); (c) OAuth2/SAML con un servidor de
  autorización dedicado.
- **Decisión tomada**: (b).
- **Justificación técnica**: (a) es más simple de implementar pero no
  demuestra el mecanismo estándar de WS-Security que el ejercicio pide
  evaluar de forma explícita (Tarea 1), y una API key estática viaja
  igual en cada petición sin ninguna protección contra reintento
  (replay); (c) es desproporcionado para proteger una única operación de
  sólo lectura en un servicio de alcance académico — introduciría un
  servidor de autorización, flujos de emisión/renovación de tokens y una
  superficie de configuración que ningún otro punto del contrato
  necesita. `PasswordDigest` nunca envía la contraseña en claro
  (`Base64(SHA1(nonce + created + password))`), y el par
  nonce+`wsu:Created` con ventana de tolerancia
  (`WSSE_NONCE_WINDOW_SECONDS`) mitiga el replay sin depender de TLS para
  ese propósito específico.
- **Riesgo o limitación**: `PasswordDigest` clásico exige que el servidor
  pueda reconstruir el mismo digest a partir de la contraseña real
  conocida — un hash unidireccional (SHA-256, bcrypt) es incompatible con
  ese perfil, porque el servidor nunca podría recuperar la contraseña
  para recalcular el digest. Una primera versión de este servicio intentó
  resolverlo usando el hash almacenado como si fuera la "password" de la
  fórmula, lo que en la práctica lo convertía en un secreto compartido
  equivalente a la contraseña (esquema "password-equivalent" tipo NTLM: 
  una fuga de esa sola fila ya permite autenticarse). Se corrigió: 
  `soap_service_credenciales.password_cifrada` guarda la contraseña
  **cifrada** (Fernet, `cryptography`) con una clave maestra
  `WSSE_MASTER_KEY` que vive solo en el `.env` del servidor, nunca en la
  base de datos. El servidor descifra para obtener la contraseña real y
  calcula el digest clásico correctamente; una fuga de solo la base de
  datos ya no basta para autenticarse (hace falta también la clave
  maestra del servidor — defensa en profundidad). Limitación restante:
  sin TLS, un atacante que capture tráfico observa qué operación se
  invocó y cuándo, aunque no el secreto en sí (eso es una limitación del
  transporte, no del perfil WS-Security).
- **Evidencia de validación**: `wsdl/library-classifier.wsdl` (comentario
  en `ObtenerEstadisticasPorModeloRequest`), `docs/CONTRATO_DISENO.md` §5
  (estructura completa de la cabecera `wsse:Security` y el esquema de
  cifrado) y `sql/soap_module.sql` (tabla `soap_service_credenciales`,
  columna `password_cifrada`). `soap/security.py` ya está implementado:
  rechaza header ausente, `UsernameToken` incompleto, digest incorrecto,
  `Created` fuera de ventana, nonce repetido y clave maestra ausente o
  incorrecta, siempre con el mismo mensaje genérico. La validación contra
  PostgreSQL real y un cliente SOAP real sigue pendiente — ver casos
  WS01–WS03 de `docs/TEST_PLAN.md`.

## ED-08. Errores vía `SOAP Fault` estructurado, no un HTTP 500 genérico

- **Necesidad/problema**: comunicar errores de negocio (concepto
  inexistente, clasificación duplicada, modelo inválido) y errores
  internos de forma que un cliente SOAP los pueda distinguir
  programáticamente, no sólo leer como texto libre.
- **Alternativas consideradas**: (a) devolver siempre HTTP 500 con un
  mensaje de texto libre en el cuerpo; (b) `<soap:Fault>` estructurado con
  `faultcode`/`faultstring`/`detail` y un código propio (`lib:
  ConceptoInexistente`, `lib:ClasificacionDuplicada`, etc.), distinguiendo
  `soap:Client` de `soap:Server`.
- **Decisión tomada**: (b).
- **Justificación técnica**: un cliente SOAP generado desde el WSDL (por
  ejemplo con Zeep) espera errores en forma de `Fault`, no un cuerpo de
  texto libre con código 500; distinguir `soap:Client` (error del
  solicitante: dato inválido, duplicado) de `soap:Server` (falla interna
  no prevista) permite que el cliente decida programáticamente si
  reintentar tiene sentido. Además, un 500 genérico sin diseño deliberado
  tiende a filtrar detalles internos (stack trace, SQL ejecutado) por
  descuido, justo lo que la regla dura de `docs/CONTRATO_DISENO.md` §4
  prohíbe explícitamente.
- **Riesgo o limitación**: exige mantener la tabla de casos de
  `docs/CONTRATO_DISENO.md` §4 disciplinadamente sincronizada con el
  código real; un caso de error nuevo que no se mapee a un código
  específico caería en el *fallback* `soap:Server`/`ErrorInterno`,
  ocultando la causa real al cliente (aunque no al log del servidor, por
  diseño).
- **Evidencia de validación**: tabla completa de faults en
  `docs/CONTRATO_DISENO.md` §4, con la regla explícita de que el detalle
  técnico real (stack trace, ruta de archivo, SQL) sólo vive en el log de
  servidor, nunca en el `Fault` enviado al cliente. `soap/faults.py` ya
  implementa exactamente las 7 subclases de la tabla
  (`ConceptoInexistenteError`, `ModeloInvalidoError`,
  `ValidacionFallidaError`, `ClasificacionDuplicadaError`,
  `XMLInvalidoError`, `AutenticacionFallidaError`, `ErrorInternoError`),
  cada una con su propio código HTTP (400/400/400/409/400/401/500 — ver
  `README.md` §3 ED-03), y `soap/service.py` captura cualquier excepción
  no prevista para nunca dejar pasar un stack trace real al cliente
  (confirmado por revisión de código). Nota: el código usa
  consistentemente el prefijo `tns` para `urn:library-classifier` dentro
  de `<detail>` en vez del `lib` del ejemplo de
  `docs/CONTRATO_DISENO.md` §4 —equivalente por especificación XML,
  documentado como tal en el propio `soap/faults.py` (ver `README.md` §3
  ED-02). Los casos negativos N01–N03 y X01 de `docs/TEST_PLAN.md` están
  diseñados para ejercitar esta tabla exactamente; su ejecución real
  contra PostgreSQL y HTTP real queda pendiente (una verificación
  funcional con dependencias simuladas ya cubrió escenarios equivalentes,
  ver `README.md` §4).

## ED-09. Interoperabilidad mediante un contrato WSDL público

- **Necesidad/problema**: que el servicio sea consumible desde un cliente
  de escritorio (Tkinter, según el enunciado) y, para la Tarea 4, desde un
  lenguaje o librería distinto sin coordinación previa con quien
  implementó el servidor.
- **Alternativas consideradas**: (a) publicar
  `wsdl/library-classifier.wsdl` en una dirección fija y estable para que
  cualquier herramienta estándar (Zeep, SoapUI, `wsimport` de Java) genere
  su propio stub cliente; (b) documentar el contrato sólo en prosa y
  esperar que cada consumidor lo reconstruya a mano leyendo este mismo
  reporte.
- **Decisión tomada**: (a).
- **Justificación técnica**: es la razón de ser de SOAP frente a un
  contrato ad-hoc: el WSDL es autocontenido (tipos XSD, mensajes,
  `portType`, `binding`, dirección del servicio) y una herramienta
  estándar puede generar un cliente funcional sin leer el código Python
  del servidor. Esto es precisamente lo que la Tarea 4 (interoperabilidad)
  necesita demostrar.
- **Riesgo o limitación**: la `soap:address location` del WSDL está fijada
  a `http://localhost:5000/soap`; si el servicio se llega a desplegar en
  otra máquina o puerto, cualquier cliente que ya generó su stub desde el
  WSDL viejo apuntará al lugar equivocado hasta que se le entregue el
  WSDL actualizado — no hay descubrimiento dinámico de servicio en este
  ejercicio.
- **Evidencia de validación**: confirmado de verdad (no simulado) el
  2026-09-03 contra el servicio corriendo en GCP con PostgreSQL real: un
  cliente Zeep externo (`tests/interop_zeep_client.py`) cargó
  `GET /wsdl`, generó su propio stub, y ejecutó las 4 operaciones —
  incluyendo el `SOAP Fault` de duplicado — sin ningún ajuste manual. Ver
  `docs/EVIDENCIA_DESPLIEGUE_REAL.md` §7 para la salida completa.

## ED-10. Bug de interoperabilidad real: namespaces XML entre cliente y servidor (encontrado y corregido)

- **Necesidad/problema**: al fin desplegar el servicio contra
  PostgreSQL/GCP reales y probarlo con el cliente de escritorio real
  (`soap_client.py`, no con `tests/test_plan.py`), `RegistrarClasificacion`
  devolvía `ValidacionFallida: El campo 'nombre' es obligatorio` a pesar
  de que el cliente sí enviaba ese campo.
- **Causa raíz**: el WSDL no declara `elementFormDefault="qualified"` en
  su `xsd:schema`, así que por la especificación XSD el valor por defecto
  es `unqualified` — el elemento RAÍZ de cada mensaje (p. ej.
  `tns:RegistrarClasificacionRequest`) va calificado con el namespace
  `tns` porque los elementos globales siempre lo están, pero sus HIJOS
  locales (`nombre`, `correo`, `bookId`, etc.) deben ir SIN namespace.
  `soap_client.py` lo implementó correctamente desde el principio;
  `soap/envelope.py`/`soap/service.py` (implementados por un proceso
  distinto, en paralelo) asumían por error que esos hijos también venían
  calificados con `tns:`. `tests/test_plan.py`, escrito por ese mismo
  proceso con el mismo supuesto equivocado en ambos lados (arma sus
  peticiones de prueba calificando los campos igual que como los lee su
  propio servidor), no lo detectó — es un caso de manual de por qué una
  prueba de integración con un cliente verdaderamente independiente
  encuentra bugs que una prueba unitaria del mismo autor no puede ver.
- **Decisión tomada**: corregir `soap/envelope.py` para que
  `get_child`/`get_text`/`make_subelement`/`set_text` usen `ns=None`
  (sin calificar) por defecto; sólo `make_element` (el elemento raíz de
  cada mensaje) sigue calificado con `tns`. `soap/service.py` no
  necesitó cambios propios: ya llamaba a esos helpers sin pasar `ns`
  explícito, así que heredó el comportamiento correcto automáticamente.
- **Justificación técnica**: es la corrección fiel a lo que el propio
  WSDL declara (o más precisamente, a lo que NO declara —
  `elementFormDefault` por omisión es `unqualified` en XML Schema), no
  un parche ad-hoc para hacer pasar una prueba puntual. Confirma además
  que sin este fix, cualquier cliente generado estrictamente a partir
  del WSDL (no sólo `soap_client.py`) habría fallado igual — de hecho el
  cliente Zeep de ED-09/Tarea 4 sólo funcionó después de aplicar este
  fix.
- **Riesgo o limitación**: ninguno conocido tras la corrección; el
  contrato (`wsdl/library-classifier.wsdl`) no cambió, sólo la
  implementación del servidor se alineó con lo que el contrato ya decía.
- **Evidencia de validación**: `python -m py_compile` sobre los archivos
  tocados, y — más importante — las tres baterías de prueba reales
  (`tests/test_plan.py`, el cliente de escritorio real, y el cliente
  Zeep) corridas después del fix, todas en PASS contra PostgreSQL/GCP
  reales. Ver `docs/EVIDENCIA_DESPLIEGUE_REAL.md` §2 para el detalle
  completo y la salida de antes/después.

## ED-11. Migración de SQL parametrizado suelto a Vistas y Stored Procedures

- **Necesidad/problema**: la Parte 6, punto 12 del enunciado exige
  explícitamente "consultas parametrizadas (Stored Procedures y
  Vistas)". La primera versión de `db/repository.py` sí usaba SQL 100%
  parametrizado (nunca concatenado), pero armaba los `JOIN`/`INSERT`
  directamente en Python con `cur.execute(...)`, sin ninguna Vista ni
  función almacenada — cumplía la letra de "parametrizado" pero no el
  mecanismo concreto que pide el enunciado.
- **Alternativas consideradas**: (a) dejarlo como estaba (SQL
  parametrizado directo, ya seguro contra inyección); (b) mover toda la
  lógica de negocio a Vistas (para lecturas) y funciones PL/pgSQL /
  `LANGUAGE sql` (para escrituras), con `soap_service_user` reducido a
  solo `EXECUTE`/`SELECT` sobre esos objetos, sin acceso directo a
  ninguna tabla.
- **Decisión tomada**: (b).
- **Justificación técnica**: además de cumplir literalmente el
  enunciado, (b) es una mejora real de mínimo privilegio: con las
  funciones marcadas `SECURITY DEFINER` (se ejecutan con los privilegios
  de quien las creó, no de quien las invoca), `soap_service_user` pasó
  de tener `SELECT` en 4 tablas del monolito y `SELECT/INSERT` en 3
  tablas propias, a no tener **ningún** privilegio directo sobre
  ninguna tabla — solo `EXECUTE` en `fn_conceptos_pendientes`,
  `fn_registrar_clasificacion`, `fn_progreso_usuario` y `SELECT` en
  `v_estadisticas_por_modelo` (más `SELECT` en
  `soap_service_credenciales`, la única excepción — ver más abajo). Una
  fuga de credenciales de `soap_service_user` ya no permite, por
  ejemplo, hacer `SELECT * FROM clasificaciones_cloud` directo: solo se
  puede invocar exactamente las operaciones que el WSDL expone.
  `fn_registrar_clasificacion` además ganó atomicidad real de motor: al
  ser una única función PL/pgSQL, si el `INSERT` final falla (duplicado
  o cualquier otra razón), PostgreSQL revierte automáticamente el upsert
  del clasificador también, sin depender de que el código Python llame a
  `conn.rollback()` en el momento correcto.
- **Criterio para la única excepción** (`obtener_credencial`, que sigue
  siendo una consulta directa a `soap_service_credenciales`): es una
  lectura de una sola tabla por clave primaria, sin `JOIN` ni lógica de
  negocio — envolver eso en una función no añade ninguna protección
  adicional (la función tendría exactamente el mismo `WHERE usuario = $1`)
  y sí añade una capa de indirección sin beneficio. El criterio aplicado
  en todo el proyecto: una vista/función cuando hay `JOIN`, cálculo de
  negocio (porcentajes, agregaciones) o una transacción de varias
  sentencias; SQL parametrizado directo cuando es una única tabla por
  clave, sin lógica adicional.
- **Riesgo o limitación**: `SECURITY DEFINER` es un patrón que, mal
  usado, puede escalar privilegios (una función SECURITY DEFINER con
  `search_path` mutable es un vector clásico de inyección de esquema).
  Mitigado con `SET search_path = public` fijo en cada función, siguiendo
  la recomendación oficial de PostgreSQL para este patrón.
- **Evidencia de validación**: `sql/soap_module.sql` aplicado sin errores
  contra `library_db` real (instancia GCP), y las mismas 12 pruebas
  reales de `docs/TEST_PLAN.md` vueltas a ejecutar después de la
  migración — ver `docs/EVIDENCIA_DESPLIEGUE_REAL.md` §11 para el
  detalle de esta segunda ronda.
