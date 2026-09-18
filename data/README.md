# data/ — esquema de la base de datos `library_db`

Aquí vive el SQL de la base compartida por el monolito, el servicio **books** (soap/REST),
la app **Electron** y el servicio **login**. **Todo cambio a la BD se registra aquí**;
no se modifica la base "a mano".

| Archivo | Uso |
|---|---|
| `schema.sql` | Esquema **canónico completo** para una instalación nueva (incluye lo del servicio login). |
| `migrations/` | Cambios incrementales para una BD **ya en marcha**. |
| `audit_schema.sql` | Solo lectura: lista tablas, llaves, vistas, funciones y permisos. Úsalo antes de cambiar nada. |
| `render-er.ps1` | Genera el diagrama ER (no se modificó). |

## Migraciones (en este orden)

| # | Archivo | Rol que lo ejecuta | Qué hace |
|---|---|---|---|
| 000 | `000_create_login_role.sql` | `postgres` | Crea el rol `login_service_user` (la contraseña llega por `-v`, no vive en el repo). |
| 001 | `001_login_service.sql` | `library_user` (dueño) | 3 columnas nullable de nombre en `users`, `CHECK`, índice único `lower(email)` y tabla `login_sessions`. |
| 002 | `002_login_email_verification.sql` | `library_user` | Columna `users.email_verified_at` y tabla `email_verifications` (confirmación del correo por Postfix). |
| 003 | `003_login_service_grants.sql` | `library_user` | Mínimo privilegio por columna para `login_service_user`. **Siempre al final**; reemplaza al antiguo `002_login_service_grants.sql`. |
| 998 | `998_rollback_002_login_email_verification.sql` | `library_user` | Deshace 002. Ejecutar **antes** que 999. |
| 999 | `999_rollback_001_login_service.sql` | `library_user` | Deshace 001 (conserva a todos los usuarios). |

```bash
# desde la raíz del monorepo (app/)
sudo -u postgres psql -d library_db -v login_password='UNA-CLAVE-LARGA' -f data/migrations/000_create_login_role.sql
export PGPASSWORD='<clave-de-library_user>'
for f in 001_login_service 002_login_email_verification 003_login_service_grants; do
  psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/$f.sql
done
```

Todas son **idempotentes** (se pueden repetir) y 001/002 corren en **una sola transacción**: si algo
falla, no queda nada a medias.

> Si ya habías aplicado un `002_login_service_grants.sql` anterior, no pasa nada: sus permisos persisten y
> `003` los completa (los `GRANT` son idempotentes). Solo hay que ejecutar los archivos nuevos `002` y `003`.

## Registro de cambios

| Fecha | Objeto | Cambio | Impacto en lo existente |
|---|---|---|---|
| 2026-09-18 | `users.nombre`, `apellido_paterno`, `apellido_materno` | Columnas `varchar(120)` **nullable** nuevas | Ninguno: el monolito nombra sus columnas explícitamente y no las ve |
| 2026-09-18 | `users` · `ck_users_person_name` | `CHECK`: o no hay nombre (los 3 NULL) o están los 3 no vacíos | Ninguno: las filas actuales (todo NULL) cumplen |
| 2026-09-18 | `users` · `uq_users_email_lower` | Índice único sobre `lower(email)` | Solo rechaza duplicados que difieran en mayúsculas (el monolito ya normaliza a minúsculas) |
| 2026-09-18 | `login_sessions` | Tabla nueva (sesiones de 30 min, revocables), FK a `users` `ON DELETE CASCADE` | Ninguno: borrar un usuario en el monolito borra también sus sesiones |
| 2026-09-18 | `users.email_verified_at` | `timestamptz DEFAULT CURRENT_TIMESTAMP`; `NULL` = correo sin confirmar | Ninguno: las cuentas existentes y las que cree el monolito quedan verificadas |
| 2026-09-18 | `email_verifications` | Tabla nueva: tokens de confirmación (solo SHA-256), vigencia y uso; FK a `users` `ON DELETE CASCADE` | Ninguno |
| 2026-09-18 | Rol `login_service_user` | Nuevo; permisos por columna solo sobre `users`, `login_sessions` y `email_verifications` | Ninguno: no recibe nada sobre books/catálogo |

**No se modificó** ninguna columna, constraint, índice, vista, función ni permiso existente, y no se ejecuta
ningún `UPDATE` sobre filas existentes.

## Por qué es seguro para books, Electron y el monolito

Se comprobó en un PostgreSQL 16 real con el esquema original de los repos
`IntegracionesLibrary` y `ejercicio05-library-soap-rest`, más datos de prueba:

- **Resultados idénticos antes/después**: `fn_listar_libros()`, `fn_libros_con_imagenes()` y
  `fn_conceptos_pendientes()` ejecutadas con el rol `soap_service_user`, y las consultas
  del monolito (login, listado de usuarios, catálogo) devolvieron exactamente lo mismo.
- **Diff de `pg_dump -s`**: cero objetos existentes cambiados; solo se añaden los nuevos (la única línea
  "distinta" es un `CHECK` existente que gana una coma final por tener un vecino nuevo).
- **Operaciones del monolito tras migrar** (crear/editar usuario, `create-admin.js`, borrar un
  usuario con sesiones y tokens) funcionan, y `uq_users_single_administrator` (máx. un admin) sigue vigente.
  Un usuario creado por el monolito después de migrar nace **verificado**.
- `schema.sql` (instalación limpia) y "esquema original + migraciones 001-002" producen la misma definición de
  `users`, `login_sessions` y `email_verifications`.
- **Rollback** probado sobre una copia: 998 y 999 devuelven `users` a sus 8 columnas originales y conservan todas las filas.
- **Permisos**: el rol del servicio es denegado al intentar leer `is_admin`, crear un administrador,
  `UPDATE`/`DELETE` sobre `users`, leer `books`, o borrar/alterar sesiones y tokens fuera de lo permitido.

`ALTER TABLE` pide un candado breve sobre `users`; 001 y 002 usan `lock_timeout = 5s` para fallar
rápido en lugar de bloquear al monolito. `email_verified_at` usa un *fast default* (PostgreSQL 11+): no reescribe la
tabla. Aun así, aplica en un momento de poco tráfico y con respaldo previo (`pg_dump library_db > respaldo.sql`).

## Decisiones de diseño

- **Se reutiliza `users`** (no se crea una tabla de contraseñas ni una segunda tabla de cuentas):
  `password_hash`, `email` único e `is_active` ya existían y pertenecen naturalmente a la cuenta.
  Las cuentas del monolito (incluido el administrador) inician sesión en el servicio login y
  viceversa: ambos usan **bcrypt** (verificado con la librería `bcrypt` de Node).
- **Confirmación del correo**: `users.email_verified_at` guarda el *estado* (dato de la cuenta) y
  `email_verifications` guarda los *tokens* (dato de cada envío: hash, vigencia, uso). Se separan porque una
  cuenta puede tener varios tokens (reenvíos) y sus atributos no dependen de la cuenta sino del token.
  Del token solo se guarda su SHA-256: una fuga de la BD no permite confirmar cuentas.
- **`DEFAULT CURRENT_TIMESTAMP` en `email_verified_at`**: hace que lo que crea el monolito (un administrador, no un
  registro público) nazca verificado sin tocar su código; el servicio login inserta `NULL` explícito en los registros
  públicos. `NULL` = "correo sin confirmar".
- **`display_name`** sigue siendo `NOT NULL` porque el monolito lo exige; el servicio login lo
  rellena con "nombre apellido_paterno apellido_materno". Es una redundancia **transitoria**
  (fase *expand*). Cuando el monolito lea las columnas atómicas, `display_name` podrá pasar a
  columna generada o vista (fase *contract*), con su propia migración.
- **Sin `last_login_at` en `users`**: es un dato derivable (`MAX(login_sessions.created_at)`);
  guardarlo violaría la normalización y exigiría mantenerlo sincronizado.
- **El servicio no puede crear administradores**: `is_admin` no está en su `INSERT` de columnas.
- **Prefijo `login_sessions`** (y no `session`) para no chocar con la tabla `session` que crea
  `connect-pg-simple` en el monolito.

## Normalización (extensión login)

- **1FN**: nombre y dos apellidos en columnas atómicas; sin listas ni grupos repetidos.
- **2FN/3FN/BCNF**:
  - `users` → determinante `user_id` (y `email`, clave candidata).
  - `login_sessions` → `session_id`; sus atributos (`expires_at`, `revoked_at`, `ip_address`…) describen a
    la sesión, no al usuario, por eso viven en tabla propia (1:N) y no se repiten en `users`.
  - `email_verifications` → `verification_id` (y `token_hash`, clave candidata); vigencia y uso dependen del token.
  - No hay dependencias transitivas.
- **Excepción documentada**: `display_name` ↔ (`nombre`, `apellido_paterno`, `apellido_materno`)
  es una dependencia derivable que se conserva por compatibilidad con el monolito (ver arriba).
- **Integridad**: `email` único sin distinguir mayúsculas, `expires_at > created_at` en sesiones y tokens,
  `token_hash` con formato SHA-256 (`CHECK`), nombres no vacíos, `ON DELETE CASCADE` de sesiones y tokens.

## Pendiente: normalizar el resto de la base

El resto del esquema (books, autores, géneros, conceptos, imágenes) ya está en 4FN según
`docs/NORMALIZATION_4NF.md` del repo `IntegracionesLibrary`, así que **no se tocó**. Si más
adelante se decide reestructurarlo, hacerlo en *expand → migrate → contract*: crear lo nuevo,
mantener lo viejo sincronizado con vistas de compatibilidad, cambiar books/Electron/monolito y
solo entonces retirar lo viejo — un archivo numerado por paso en `migrations/`, con su rollback.
