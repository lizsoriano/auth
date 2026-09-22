# Contrato y decisiones de diseño — módulo SOAP de clasificación Cloud

Fuente de verdad para quien implemente `soap/`, el cliente de escritorio y
la documentación. Si algo en el código contradice este archivo, este
archivo gana (o se actualiza explícitamente y se explica por qué).

## 1. Alcance

Ver el enunciado (`ENUNCIADO_EJERCICIO04.md` si se copia al proyecto).
Resumen operativo: módulo Flask independiente, construye SOAP a mano con
`xml.etree.ElementTree`, comparte `library_db` (PostgreSQL) con el
monolito Node.js de `integracion02/apps/web-monolito` **sin modificarlo**.

Carpeta del proyecto: `library_soap_service/` (hermana de `integracion02/`
y `portafolio/`, dentro de `integracionAplicaciones/`).

## 2. Operaciones (WSDL: `wsdl/library-classifier.wsdl`)

1. **ObtenerConceptosPendientes** — lectura de `book_concepts` + `concepts`
   + `books` + `categories`. Si `filtroCorreo` viene, excluye lo que ese
   correo ya tenga en `clasificaciones_cloud` (join por `clasificador.correo`
   → `clasificaciones_cloud.clasificador_id`). Sin autenticación.
2. **RegistrarClasificacion** — valida, hace upsert de `clasificadores` por
   correo (si no existe, lo crea con nombre/apellidos dados; si existe,
   no pisa nombre/apellidos con datos distintos — usar el registro
   existente y loguear si difieren), inserta en `clasificaciones_cloud`
   dentro de una transacción, y llama
   `fn_registrar_peticion_cliente(tipoCliente, correo)`. Duplicado →
   SOAP Fault 409 (ver §4). Sin autenticación (dato de negocio, no
   sensible — ver auditoría §6).
3. **ObtenerProgresoUsuario** — cuenta total de conceptos clasificables
   (todo `book_concepts`) vs. cuántos clasificó ese correo. Sin
   autenticación.
4. **ObtenerEstadisticasPorModelo** (Tarea 1, trabajo en casa) —
   `COUNT(*) GROUP BY modelo_cloud` sobre `clasificaciones_cloud`.
   **Requiere WS-Security** (§5). Es la única operación protegida: agrega
   valor analítico agregado, no es un dato de catálogo público como las
   otras tres.

## 3. Acceso a datos

- Un único módulo `db/` con `psycopg2`, conexión nueva por request (ver
  ED-01 en `docs/ENGINEERING_DECISIONS.md`).
- **Toda la lógica de negocio vive en Vistas y funciones PL/pgSQL**
  (`fn_conceptos_pendientes`, `fn_registrar_clasificacion`,
  `fn_progreso_usuario`, `v_estadisticas_por_modelo` — todas en
  `sql/soap_module.sql`), nunca en `JOIN`/`INSERT` sueltos armados en
  Python — así lo exige la Parte 6, punto 12 del enunciado. `db/repository.py`
  solo invoca esas funciones/vistas con parámetros posicionales (`%s`,
  nunca f-string/concat). Ver ED-11 para la justificación completa,
  incluida la única excepción (`obtener_credencial`, una lectura simple
  por clave primaria sin `JOIN`).
- `RegistrarClasificacion` → `fn_registrar_clasificacion(...)`: la
  transacción completa (verificar concepto → upsert clasificador →
  `INSERT` en `clasificaciones_cloud` → contar cliente) vive dentro de
  una sola función PL/pgSQL atómica — si algo falla, PostgreSQL revierte
  todo automáticamente, sin `BEGIN`/`COMMIT`/`ROLLBACK` explícitos
  coordinados desde Python. La `UNIQUE (clasificador_id, book_id, concept_id)`
  de `sql/soap_module.sql` sigue siendo lo que dispara `UniqueViolation`
  en duplicado.
- Variables de conexión en `.env` (ver `.env.example`), nunca hardcodeadas
  ni commiteadas. Usuario de BD: `soap_service_user` (creado en
  `sql/soap_module.sql`), **no** `postgres` ni el rol del monolito — y,
  desde ED-11, sin ningún privilegio directo sobre tablas: solo
  `EXECUTE`/`SELECT` en las funciones y vistas de arriba.

## 4. SOAP Fault — tabla de casos

| Caso | faultcode | Subcódigo (detalle) | Comportamiento |
|---|---|---|---|
| Concepto/libro inexistente | `soap:Client` | `lib:ConceptoInexistente` | No ejecuta INSERT. Mensaje: "El concepto indicado no existe para ese libro." |
| `modeloCloud` fuera de IaaS/PaaS/SaaS/FaaS | `soap:Client` | `lib:ModeloInvalido` | Validado antes de tocar BD. |
| Campo obligatorio ausente/vacío (nombre, correo, etc.) | `soap:Client` | `lib:ValidacionFallida` | Igual, sin llegar a SQL. |
| Correo con formato inválido | `soap:Client` | `lib:ValidacionFallida` | Regex simple, mismo criterio que el CHECK de `clasificadores`. |
| Clasificación duplicada (mismo clasificador + concepto) | `soap:Client` | `lib:ClasificacionDuplicada` | Captura `psycopg2.errors.UniqueViolation` sobre `uq_clasificaciones_sin_duplicado`; el detail incluye `httpStatusEquivalente: 409`. |
| XML mal formado / operación desconocida | `soap:Client` | `lib:XMLInvalido` | `ET.ParseError` capturado antes de tocar BD; nunca se ejecuta SQL. |
| WS-Security ausente/credenciales inválidas en `ObtenerEstadisticasPorModelo` | `soap:Client` | `lib:AutenticacionFallida` | Ver §5. |
| Falla de PostgreSQL no prevista (conexión caída, etc.) | `soap:Server` | `lib:ErrorInterno` | Mensaje genérico al cliente ("Error interno del servicio, intente más tarde"); el detalle técnico real (excepción, query) se registra **solo** en el log del servidor (`logging`, nunca en el Fault). |

Regla dura: el `<faultstring>`/`<detail>` enviado al cliente **nunca**
contiene stack trace, ruta de archivo, contraseña, cadena de conexión ni
el SQL ejecutado. Eso vive únicamente en el log de servidor
(`soap/faults.py` + `logging` configurado en `app.py`).

Estructura SOAP 1.1 de Fault a usar (namespace `soap` =
`http://schemas.xmlsoap.org/soap/envelope/`):

```xml
<soap:Fault>
  <faultcode>soap:Client</faultcode>
  <faultstring>El concepto indicado no existe para ese libro.</faultstring>
  <detail>
    <lib:Error xmlns:lib="urn:library-classifier">
      <lib:codigo>ConceptoInexistente</lib:codigo>
    </lib:Error>
  </detail>
</soap:Fault>
```

## 5. WS-Security (Tarea 1)

Perfil elegido: **UsernameToken con PasswordDigest** (perfil clásico de
WS-Security 1.0), no texto plano, no un simple header custom, para que el
ejercicio demuestre el mecanismo real y nunca exponga la contraseña en la
red.

Cabecera esperada en `soap:Header`:

```xml
<soap:Header>
  <wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
    <wsse:UsernameToken>
      <wsse:Username>reportes</wsse:Username>
      <wsse:Password Type="...#PasswordDigest">BASE64(SHA1(nonce + created + password))</wsse:Password>
      <wsse:Nonce EncodingType="...#Base64Binary">BASE64(random-bytes)</wsse:Nonce>
      <wsu:Created xmlns:wsu="...oasis-200401-wss-wssecurity-utility-1.0.xsd">2026-09-03T12:00:00Z</wsu:Created>
    </wsse:UsernameToken>
  </wsse:Security>
</soap:Header>
```

- El servicio guarda la contraseña de cada usuario de reportes **cifrada**
  (no hasheada) en `soap_service_credenciales.password_cifrada`, con
  Fernet (AES simétrico autenticado, paquete `cryptography`) usando una
  clave maestra `WSSE_MASTER_KEY` que vive solo en la variable de entorno
  del servidor — nunca en la base de datos ni en el repositorio. Un hash
  unidireccional (SHA-256, bcrypt) es **incompatible** con PasswordDigest:
  ese perfil exige que el servidor pueda reconstruir el digest a partir de
  la contraseña real, y si en su lugar se usara el hash almacenado como
  "password" en la fórmula, ese hash pasaría a ser el secreto de
  autenticación real — ni más ni menos seguro que guardar la contraseña en
  claro. El cifrado reversible con clave separada de la base de datos sí
  permite validar el perfil correctamente y mantiene la propiedad de que
  una fuga de solo la base de datos no basta para autenticarse.
- Validación del digest: el servidor descifra `password_cifrada` con
  `WSSE_MASTER_KEY` para recuperar la contraseña real, recalcula
  `Base64(SHA1(Base64Decode(nonce) + created + password_real))` y
  compara con el valor recibido. `created` debe estar dentro de una
  ventana de tolerancia razonable (p. ej. 5 minutos) para mitigar replay.
- Nonce usado una sola vez: mantener en memoria (dict con expiración) o
  tabla auxiliar los nonces vistos en la ventana de tolerancia; si se
  repite, es replay → `lib:AutenticacionFallida`.
- Implementar en `soap/security.py`, desacoplado de `soap/service.py`
  (el service solo pregunta `security.validar_header(header_element)`).
- Documentar en el reporte: qué pasa con credenciales incorrectas
  (capturas + SOAP Fault, no un 500 genérico).

## 6. Auditoría del contrato (resumen — detalle completo va en el reporte, Tarea 3)

| Dato | ¿Se expone? | Dónde | Justificación |
|---|---|---|---|
| `books.isbn`, `books.title` | Sí | ObtenerConceptosPendientes | El clasificador necesita saber qué libro está viendo. |
| `categories.name` | Sí | ObtenerConceptosPendientes | Contexto para elegir el concepto correcto. |
| `concepts.name`, `book_concepts.definition` | Sí | ObtenerConceptosPendientes | Es literalmente lo que hay que clasificar. |
| `books.price`, `books.stock` | No | — | Irrelevante para clasificar; dato comercial del monolito. |
| `users.*` (login web del monolito) | No | — | El módulo SOAP no reutiliza `users`; tiene su propia tabla `clasificadores`, sin contraseña. |
| `clasificadores.correo` | Solo como identificador de negocio (no se expone el listado completo a terceros) | ObtenerProgresoUsuario (eco del propio correo consultado) | Es el dato con el que el cliente se identifica; no hay un endpoint que liste todos los correos. |
| Cadena de conexión / credenciales de BD | No, nunca | — | Ni en respuestas ni en Faults. |
| Hash de contraseña WS-Security | No | — | Solo vive en `soap_service_credenciales`; nunca sale del servidor. |

## 7. Convenciones de código

- Español en nombres de tablas/columnas propias y en mensajes al usuario;
  inglés está bien en nombres de variables/funciones Python si ya es la
  convención del archivo (seguir el estilo de `integracion02`, que mezcla
  comentarios en español con código en inglés).
- `xml.etree.ElementTree` únicamente para XML — nada de Spyne/Zeep en el
  servidor (Zeep sí se usa después, del lado cliente, para la Tarea 4 de
  interoperabilidad — eso es un consumidor externo, no el servicio).
- Namespaces SOAP en todo el código, nunca strings XML concatenados a mano
  con datos de usuario sin pasar por `ET.SubElement(...).text = valor`
  (que sí escapa automáticamente).

## 8. Config / entorno

`.env.example` (a crear junto al `app.py`):

```
FLASK_ENV=development
SOAP_PORT=5000
DATABASE_URL=postgresql://soap_service_user:CAMBIAR@localhost:5432/library_db
LOG_LEVEL=INFO
WSSE_NONCE_WINDOW_SECONDS=300
```

Puerto sugerido `5000` (el monolito ya usa `3000` según
`integracion02/apps/web-monolito/.env.example`) para poder correr ambos
en la misma máquina de desarrollo sin choque.
