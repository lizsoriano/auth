# library_soap_service

## Actividad en clase: microservicio bilingüe (XML + JSON)

Extensión sobre el microservicio SOAP ya entregado (Ejercicio Guiado 03):
ahora también responde en JSON cuando se pide `?format=json`, sin dejar
de responder XML por defecto. `GET /wsdl` y `POST /soap` **no cambiaron**.

Rutas nuevas (`app.py` + `rest_api.py`):

| Ruta | XML (por defecto) | `?format=json` |
|---|---|---|
| `GET /books` | lista de libros | idem en JSON |
| `GET /books/<isbn>` | un libro (404 si no existe) | idem en JSON |
| `GET /concepts` | conceptos Cloud (IaaS/PaaS/SaaS/FaaS) + datos del libro | idem en JSON |
| `GET /books/images` | libros con sus imágenes | idem en JSON |

Acceso a datos nuevo: `db/repository.py` (`listar_libros`,
`listar_libros_con_imagenes`) más `sql/ejercicio05_extension.sql`, que es
**puramente aditivo** sobre `sql/soap_module.sql` — agrega dos funciones
`SECURITY DEFINER` (`fn_listar_libros`, `fn_libros_con_imagenes`) y solo
otorga `EXECUTE` sobre ellas a `soap_service_user` (mismo criterio de
mínimo privilegio del resto del proyecto: nunca `SELECT` directo sobre
tablas). El endpoint `/concepts` no necesitó SQL nuevo: reutiliza
`fn_conceptos_pendientes` ya existente, llamada sin filtros.

Para aplicar la extensión sobre una `library_db` ya poblada:

```bash
psql -h localhost -U library_user -d library_db -f sql/ejercicio05_extension.sql
```

**Verificado de verdad**, no solo localmente: desplegado y probado contra
la instancia real de GCP (`maquina-02`, PostgreSQL de producción con el
seed real de 30 libros), las 4 rutas exactas pedidas más las 2
adicionales, en ambos formatos, incluyendo el caso 404. `GET /wsdl` y
`POST /soap` se re-verificaron sin cambios de comportamiento.

---

Módulo SOAP de clasificación Cloud del catálogo de la librería. Se integra
por **base de datos compartida** (PostgreSQL, `library_db`) con el
monolito Node.js de `integracion02/apps/web-monolito`, sin modificarlo.
Construye SOAP a mano con `xml.etree.ElementTree` (nada de
Spyne/Zeep en el servidor).

Fuentes de verdad del contrato — léelas antes de tocar el código:
- `wsdl/library-classifier.wsdl` — operaciones y tipos exactos.
- `docs/CONTRATO_DISENO.md` — reglas de negocio, tabla de SOAP Fault,
  perfil WS-Security, variables de entorno.
- `sql/soap_module.sql` — tablas propias del módulo y rol `soap_service_user`.

## 1. Puesta en marcha

### 1.1 Requisitos

- Python 3.10+ (probado con 3.12).
- PostgreSQL 13+, con `library_db` ya creada y poblada por
  `integracion02/db/00_create_database.sql` a `06_views.sql` (en orden).

### 1.2 Entorno virtual y dependencias

```bash
cd library_soap_service
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 1.3 Base de datos

Con `library_db` ya poblada por `integracion02/db`, aplica encima las
tablas propias de este módulo:

```bash
PGPASSWORD=<superusuario> psql -h localhost -U <superusuario> -d library_db -f sql/soap_module.sql
```

Esto crea `clasificadores`, `clasificaciones_cloud`, `clientes_servidos`,
`soap_service_credenciales`, la función `fn_registrar_peticion_cliente` y
el rol `soap_service_user` (con privilegios mínimos — ver la nota de
auditoría al final de `sql/soap_module.sql`).

Cambia la contraseña de `soap_service_user` (la del script trae un
placeholder `CAMBIAR_EN_.env_NO_COMMITEAR`):

```sql
ALTER ROLE soap_service_user WITH PASSWORD 'la-que-pongas-en-tu-.env';
```

### 1.4 Variables de entorno

```bash
cp .env.example .env
```

Y edita `DATABASE_URL` con la contraseña real de `soap_service_user`.
Variables usadas (ver `config/settings.py`):

| Variable | Uso |
|---|---|
| `FLASK_ENV` | `development` activa el modo debug de Flask. |
| `SOAP_HOST` / `SOAP_PORT` | dirección donde escucha el servicio (puerto sugerido `5000`, el monolito ya usa `3000`). |
| `DATABASE_URL` | cadena de conexión de `soap_service_user` a `library_db`. |
| `LOG_LEVEL` | nivel de `logging` (aquí es donde va el detalle técnico real de cualquier error, nunca en un SOAP Fault). |
| `WSSE_NONCE_WINDOW_SECONDS` | ventana de tolerancia (segundos) para `wsu:Created` y para deduplicar `wsse:Nonce` en WS-Security. |

### 1.5 Arrancar el servicio

```bash
python app.py
```

- WSDL: `GET http://127.0.0.1:5000/wsdl`
- Endpoint SOAP: `POST http://127.0.0.1:5000/soap`

### 1.6 Crear un usuario de reportes (WS-Security)

`ObtenerEstadisticasPorModelo` es la única operación protegida. Antes de
crear una credencial, genere y guarde en `.env` una clave maestra:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# copiar el valor impreso a WSSE_MASTER_KEY= en .env
```

Complete también `ADMIN_DATABASE_URL` en `.env` (el mismo superusuario que
usó para aplicar `sql/soap_module.sql`) — `soap_service_user`, el rol que
usa el servicio en ejecución (`DATABASE_URL`), es de solo lectura en
`soap_service_credenciales` a propósito, así que este script necesita una
conexión aparte con privilegios de escritura.

Luego, para poder invocarla hace falta una fila en `soap_service_credenciales`:

```bash
python scripts/crear_credencial_reportes.py --usuario reportes --password "unaClaveSegura123"
```

El cliente SOAP debe usar esa MISMA contraseña en claro (no un valor
derivado) para construir su `UsernameToken`/`PasswordDigest` — el
servidor la guarda cifrada (no hasheada) y la descifra con
`WSSE_MASTER_KEY` para validar. Ver la sección WS-Security más abajo
para el porqué.

### 1.7 Correr el plan de pruebas

Con el servicio corriendo y la base poblada:

```bash
python tests/test_plan.py
```

Manda peticiones SOAP reales por `http.client` (sin `requests`) y
comprueba P01, P02, N01 (duplicado → 409), N02 (concepto inexistente →
400) y N03 (modeloCloud inválido → 400). Imprime `PASS`/`FAIL` por caso.

## 2. Estructura

```
app.py                  # arranca Flask, GET /wsdl, POST /soap
config/settings.py       # .env -> Config, configure_logging()
db/connection.py         # get_connection() (psycopg2, conexión por request)
db/repository.py         # una función por operación del WSDL, SQL parametrizado
db/errors.py             # ConceptoInexistenteError, ClasificacionDuplicadaError
soap/envelope.py         # helpers Envelope/Header/Body (ElementTree puro)
soap/service.py          # parseo, validación, dispatch, construcción de respuesta
soap/faults.py           # SoapFaultError y subclases, build_fault_bytes()
soap/security.py         # WS-Security UsernameToken/PasswordDigest
scripts/crear_credencial_reportes.py
tests/test_plan.py
```

## 3. Decisiones de diseño (formato Necesidad → Decisión → Justificación)

**ED-01 — Conexión a BD por request, sin pool.**
Necesidad: cada operación SOAP necesita una conexión a `library_db`.
Decisión: `db/connection.get_connection()` abre y cierra una conexión
psycopg2 por petición (context manager).
Justificación: el volumen esperado de peticiones de este ejercicio es
bajo; un pool añadiría complejidad sin beneficio real. Si el módulo
creciera, `get_connection()` es el único punto que habría que cambiar
por un `SimpleConnectionPool`.

**ED-02 — Prefijo XML único (`tns`) también para los Fault, en vez de `lib`.**
Necesidad: el ejemplo de `docs/CONTRATO_DISENO.md` §4 usa `xmlns:lib` para
`urn:library-classifier` dentro de `<detail>`.
Decisión: usar consistentemente el prefijo `tns` (ya registrado para ese
mismo namespace en `soap/envelope.py`) en todo el documento, Fault
incluido.
Justificación: por especificación XML, lo que identifica un namespace es
la URI, no la letra del prefijo — un cliente SOAP correcto compara
`urn:library-classifier`, no el string `"lib"`. Usar un único prefijo en
todo el documento evita declaraciones de namespace redundantes y
simplifica `soap/faults.py`. Documentado también como comentario en el
propio archivo.

**ED-03 — Mapeo de SOAP Fault a HTTP status.**
Necesidad: el contrato solo fija explícitamente un HTTP status (`409`
para `ClasificacionDuplicada`, y así lo confirma el enunciado del plan
de pruebas: "N01 duplicado → 409"). Para el resto de los códigos de
Fault no hay una tabla explícita de status HTTP.
Decisión (`soap/faults.py`):
| codigo | http_status |
|---|---|
| ConceptoInexistente, ModeloInvalido, ValidacionFallida, XMLInvalido | 400 |
| ClasificacionDuplicada | 409 (el único explícito en el contrato) |
| AutenticacionFallida | 401 |
| ErrorInterno | 500 |
Justificación: SOAP 1.1 "puro" recomendaría 500 para cualquier Fault,
pero el contrato pide diferenciar al menos el caso 409; para mantener el
criterio consistente se usan los códigos HTTP semánticamente más
cercanos a cada `soap:Client` (400 = bad request del cliente, 401 =
fallo de autenticación) y se deja 500 solo para `soap:Server`
(`ErrorInterno`), igual que en cualquier API HTTP convencional. Esto es
lo que consume `tests/test_plan.py` para decidir PASS/FAIL.

**ED-04 — WS-Security PasswordDigest sobre una contraseña cifrada (reversible), no un hash.**
Necesidad: el contrato exige simultáneamente (a) que el servidor nunca
guarde la contraseña en claro "a la vista" en la base de datos, y (b)
que valide el `PasswordDigest` clásico de WS-Security, que por
definición recalcula `SHA1(nonce + created + password)` del lado
servidor — lo que requiere la contraseña real, no un hash irreversible.
Un hash unidireccional (SHA-256, bcrypt) es incompatible con ese perfil:
si se usara el hash mismo como "password" en la fórmula, ese hash pasaría
a ser el secreto de autenticación real, ni más ni menos seguro que
guardar la contraseña en claro (una fuga de esa sola fila ya permite
autenticarse, sin necesitar jamás la contraseña original).
Decisión (`soap/security.py`, `sql/soap_module.sql`): la contraseña se
guarda **cifrada** (no hasheada) en `soap_service_credenciales.password_cifrada`
con Fernet (`cryptography`, AES simétrico autenticado), usando una clave
maestra `WSSE_MASTER_KEY` que vive solo en la variable de entorno del
servidor — nunca en la base de datos ni en el repositorio. Para validar,
el servidor descifra con esa clave, recupera la contraseña real, y con
ella calcula `digest = Base64(SHA1(Base64Decode(nonce) + created + password_real))`.
Justificación: es la forma correcta de implementar PasswordDigest (el
servidor sí puede reconstruir el digest real) y a la vez cumple la
intención de "no contraseña en claro a simple vista en la BD": una fuga
de solo la base de datos no basta para autenticarse, hace falta también
la clave maestra del servidor (defensa en profundidad). Efecto práctico:
cualquier cliente que consuma `ObtenerEstadisticasPorModelo` (incluida
la Tarea 4 de interoperabilidad) necesita la contraseña original en
claro (la misma que se pasó a `crear_credencial_reportes.py`), no ningún
valor derivado — al revés de la primera versión de esta decisión.

**ED-05 — `identificador` de `fn_registrar_peticion_cliente` = correo.**
Necesidad: la función SQL recibe `(tipo_cliente, identificador)` pero el
WSDL de `RegistrarClasificacionRequest` no trae un campo `identificador`
explícito.
Decisión: se usa `correo` como `identificador`, tal como lo indica
literalmente `docs/CONTRATO_DISENO.md` §2 ("...y llama
`fn_registrar_peticion_cliente(tipoCliente, correo)`"). No fue una
decisión libre — el contrato ya lo especifica; se documenta aquí solo
para que quede explícito en el código (`db/repository.py`).

**ED-06 — Validaciones de formato en operaciones "sin autenticación" que llevan correo.**
Necesidad: la tabla de Fault menciona "Correo con formato inválido" como
`ValidacionFallida` sin decir en qué operaciones aplica.
Decisión: se valida el formato de correo (mismo regex que el CHECK de
`clasificadores` en `sql/soap_module.sql`) en las tres operaciones que
reciben un correo como entrada: `RegistrarClasificacion`,
`ObtenerProgresoUsuario`, y — si viene — `filtroCorreo` de
`ObtenerConceptosPendientes`.
Justificación: consistencia con la restricción real de la base de datos
y con la única fila de la tabla de Fault que menciona formato de correo.

## 4. Qué se verificó realmente (y qué no)

Este entorno de desarrollo **no tiene** `pip` funcional, ni PostgreSQL,
ni las dependencias del proyecto instaladas (`flask`, `psycopg2-binary`,
`python-dotenv`). Se verificó honestamente:

1. `python -m py_compile` sobre los 14 archivos `.py` del proyecto — sin
   errores de sintaxis.
2. `xml.etree.ElementTree.parse('wsdl/library-classifier.wsdl')` — el
   WSDL es XML bien formado (no se modificó ese archivo).
3. Una verificación funcional adicional (fuera del repo, en scratchpad,
   no forma parte del entregable) que reemplaza `psycopg2`/`dotenv` por
   módulos falsos mínimos para poder importar y ejecutar de verdad
   `soap/service.py`, `soap/envelope.py`, `soap/faults.py` y
   `soap/security.py` con `db/repository.py` monkeypencheado (sin BD
   real). Cubrió 14 casos: round-trip de Envelope con escape de XML,
   XML mal formado, operación desconocida, campo obligatorio ausente,
   modeloCloud inválido (confirmando que NO se llama a la capa de BD),
   camino feliz de `RegistrarClasificacion`, propagación de
   `ConceptoInexistenteError`/`ClasificacionDuplicadaError` desde `db/`
   hasta el Fault correcto (incluyendo `httpStatusEquivalente`), no fuga
   de detalles internos en un error no previsto (500 genérico), y el
   ciclo completo de WS-Security (digest correcto → 200, digest
   incorrecto → 401, sin header → 401). Los 14 casos dieron PASS.

**Lo que queda pendiente de verificar contra una base real** (no se pudo
hacer en este entorno):
- Que `sql/soap_module.sql` aplique sin errores sobre una `library_db`
  ya poblada por `integracion02/db`.
- Las consultas SQL reales de `db/repository.py` (sintaxis revisada a
  mano, pero no ejecutada contra PostgreSQL).
- `psycopg2.errors.UniqueViolation` disparándose de verdad ante un
  `INSERT` duplicado (en la verificación funcional se simuló con un
  monkeypatch de la función completa, no con el driver real).
- `tests/test_plan.py` de punta a punta contra el servicio corriendo.

No se modificó `sql/soap_module.sql` ni `wsdl/library-classifier.wsdl`
ni `docs/CONTRATO_DISENO.md`: no se encontró ningún error real de
sintaxis SQL al leerlos.

## 5. Documentación adicional

- [`docs/CONTRATO_DISENO.md`](docs/CONTRATO_DISENO.md) — decisiones de
  diseño del contrato ya tomadas (fuente de verdad; no modificar sin
  releer el porqué).
- [`docs/ENGINEERING_DECISIONS.md`](docs/ENGINEERING_DECISIONS.md) —
  registro de decisiones de ingeniería de más alto nivel (elección de
  stack, SOAP vs REST/GraphQL, contract-first, WS-Security, SOAP Fault
  vs. HTTP 500, interoperabilidad), formato Necesidad→Alternativas→
  Decisión→Justificación→Riesgo→Evidencia. Complementa, sin repetir, las
  decisiones de implementación más puntuales de la sección 3 de este
  README (estrategia de conexión, prefijo XML, mapeo de status HTTP,
  adaptación del digest WS-Security).
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) y
  [`docs/ARCHITECTURE_DIAGRAM.puml`](docs/ARCHITECTURE_DIAGRAM.puml) —
  macro-arquitectura, fronteras de responsabilidad entre este módulo y
  el monolito, y diagrama de componentes en PlantUML (sin renderizar en
  este entorno; instrucciones para hacerlo en la propia máquina del
  usuario dentro del documento).
- [`docs/WSDL_AUDIT.md`](docs/WSDL_AUDIT.md) — auditoría de exposición de
  datos campo por campo de las 4 operaciones del WSDL (Tarea 3), con
  riesgos de seguridad/acoplamiento identificados y su mitigación
  propuesta.
- [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md) — matriz de pruebas formal
  (todos los casos en `PENDING` frente a PostgreSQL/servicio reales;
  ver ahí la relación con la verificación funcional simulada de la
  sección 4 de este README, que es un ejercicio de confianza adicional
  fuera del entregable, no un reemplazo de la ejecución real).
