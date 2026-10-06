# JWT + Redis en los microservicios de Library

Referencia única de los dos ejercicios guiados (**Servicios** y **Redis**): qué se guarda dónde, qué pasa cuando
algo falla y quién puede hacer qué. El código común vive en [`services/shared/library_common`](../services/shared).

## 1. Servicios y puertos

| Servicio | Puerto | Prefijo nginx | Base de datos (rol propio, solo `EXECUTE` de funciones) |
|---|---|---|---|
| login | 5000 | `/auth/` | `login_service_user` |
| books (`services/soap`) | 5001 | `/soap/` | `soap_service_user` |
| users | 5002 | `/users/` | `users_service_user` |
| authors | 5003 | `/authors/` | `authors_service_user` |
| pedidos | 5004 | `/pedidos/` | `pedidos_service_user` |
| pagos | 5005 | `/pagos/` | `pagos_service_user` |

Los servicios **no se llaman entre sí por HTTP**: comparten PostgreSQL (fuente de verdad), el secreto JWT y Redis.

## 2. JWT

- HS256, firmado con `JWT_SECRET_KEY` (variable de entorno, misma en los 6 servicios, ≥ 32 caracteres, nunca en el código).
- Claims: `iss`, `sub`, `user_id`, `role_id`, `role`, `iat`, `exp` (20 min) y `jti`.
- Cada servicio valida **algoritmo (solo HS256), firma, `exp`, `iat`, `iss`, `jti`, `user_id`, `role_id`** y consulta
  `jwt:revoked:<jti>` en Redis.
- Renovación: `POST /auth/token/refresh` con el refresh token (opaco, un solo uso, rotación). La sesión muere a las 24 h.

| Situación | Respuesta |
|---|---|
| Sin `Authorization`, esquema ≠ Bearer, firma mala, `alg=none`, expirado, claims faltantes, `jti` revocado | **401** |
| Token válido pero rol insuficiente / recurso ajeno | **403** (o 404 si no debe revelarse que existe) |
| Redis no responde (no se puede comprobar la revocación) | **503** (falla cerrado) |

### Matriz de roles (`role_id`: 1 admin · 2 staff · 3 customer)

| Servicio | GET | POST / PUT / PATCH / DELETE |
|---|---|---|
| books | público | admin, staff |
| authors | público | admin, staff |
| users | admin (lista); cada quien su propia cuenta | admin; un usuario modifica solo su perfil/contraseña |
| pedidos | JWT; customer ve solo los suyos, staff/admin todos | customer crea/cancela los suyos; cambios de estado según rol |
| pagos | JWT; customer ve solo los suyos | JWT; customer paga solo sus pedidos; `PUT/PATCH/DELETE` → 405 |

## 3. Claves de Redis

| Clave | Contenido | TTL | Si Redis falla |
|---|---|---|---|
| `session:<sid>` | JSON de la sesión (usuario, `jti` vigente) | 30 min deslizantes | 503 (login/refresh/logout/extend) |
| `refresh:<sha256>` | usuario + sesión (solo el hash del token) | 24 h | 503 |
| `jwt:revoked:<jti>` | marca de revocación | vida restante del JWT | 503 en cualquier ruta protegida |
| `books:list:all`, `books:<isbn>` | respuesta normalizada (independiente de XML/JSON) | 60 s | se lee de PostgreSQL (abre) |
| `authors:list:<limit>`, `authors:<id>` | idem | 60 s | se lee de PostgreSQL (abre) |
| `lock:order:<id>` | candado `SET NX EX`, se libera con compare-and-delete | 10 s | 503 |
| `payment:idem:<user>:<key>` | `pending` (60 s) → resultado (24 h) | 60 s / 24 h | 503, no se cobra sin Redis |

**Invalidación:** tras cada escritura exitosa se borra `books:<isbn>` y `books:list:*`; authors y pedidos también
invalidan `books:*` (el autor y el stock salen en el libro). Un error de Redis al invalidar no tumba la escritura
(el TTL de 60 s acota el desfase).

**Política de fallo:** Redis es *opcional* solo para lecturas cacheadas (`GET` públicos siguen por PostgreSQL).
Sesión, revocación, autorización, candados e idempotencia **fallan cerrado**: preferimos un 503 a aceptar un token revocado
o cobrar dos veces. Timeouts de 1 s y `ConnectionPool` para no colgar peticiones.

**Configuración de Redis en la VM** (`deploy/setup_microservices_vm.sh`): solo loopback, `requirepass`, `appendonly yes` +
`appendfsync everysec` (la revocación sobrevive a un reinicio), `maxmemory 128mb` con `noeviction` (nunca se expulsa una
sesión o una revocación para hacer sitio).

## 4. Idempotencia de pagos (dos capas)

1. Redis `payment:idem:...` evita la doble ejecución concurrente y reproduce la respuesta (`Idempotent-Replay: true`).
2. `payments.idempotency_key` es `UNIQUE` en PostgreSQL: aunque Redis perdiera la clave, no hay doble cobro.
Reusar la clave con otro cuerpo → 409 (huella distinta).

## 5. Observabilidad y seguridad transversal

- **Un solo proceso por servicio:** cada unidad de systemd corre `gunicorn -w 1 --threads 4`. Los contadores de `/metrics` viven en la memoria del proceso; con 2 procesos cada uno contaba solo lo suyo y `/metrics` podía mostrar 0 aunque el otro proceso sí hubiera rechazado tokens. Los hilos dan concurrencia (cada consulta abre su propia conexión a PostgreSQL y el cliente de Redis usa un pool, así que es seguro).
- `GET /health` (incluye Redis y PostgreSQL) y `GET /metrics` (texto estilo Prometheus, solo admin): aciertos/fallos de caché,
  errores de Redis, tokens rechazados/revocados.
- `CORS_ORIGINS` explícito en cada servicio (vacío = ningún origen). Respuestas autenticadas con `Cache-Control: no-store`.
- Los logs registran `user_id` y `jti`, **nunca** contraseñas, tokens ni el header `Authorization`
  (se eliminó el log que lo escribía completo en `services/soap`).
- HTTPS: terminación en nginx; ver `deploy/README.md` (sin dominio no hay Let's Encrypt: certificado autofirmado).

## 6. Cómo probarlo

- Unitarias por servicio: `pytest` en cada carpeta (Redis simulado con `fakeredis`; las de PostgreSQL real requieren `TEST_DATABASE_URL`).
- De punta a punta con Docker (PostgreSQL + Redis + 6 servicios): `bash e2e/run_local.sh`.
- En la VM, con la caída real de Redis: `bash deploy/evidencias_microservicios.sh`.
