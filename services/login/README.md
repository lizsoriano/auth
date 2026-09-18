# login — microservicio de autenticación (Library)

Registro, confirmación del correo, inicio/cierre de sesión y consulta de sesión para la plataforma de
librería. **Independiente**: tiene su propio entorno, dependencias y arranque; solo comparte la base de
datos PostgreSQL (`library_db`) con el monolito, books (soap/REST) y Electron. Se integrará con ellos más adelante.

- **Stack**: Python 3.10+, Flask, Psycopg 3, PostgreSQL 13+, bcrypt.
- **Puerto**: **5000**. (soap/books usa 5001; el monolito, 3000.)
- **Formatos**: todas las respuestas en **XML** (por defecto) o **JSON** con `?format=json`. No hay interfaz
  gráfica: lo único que se ve son estas respuestas (también al abrir el enlace del correo en el navegador).
- **Sesión**: cookie de Flask, dura **30 minutos**; al caducar responde `session_expired`.
- **Correo**: la confirmación se envía por el **Postfix de la instancia** (`postfix.service`, `localhost:25`).
  No usa POP ni la API de Gmail.
- **Swagger**: `http://localhost:5000/docs/` (spec OpenAPI en `/openapi.json`).

```
services/login/
├── app.py                     # punto de entrada (gunicorn: app:app)
├── login_service/
│   ├── config.py              # variables de entorno → Settings (valida al arrancar)
│   ├── repository.py          # acceso a PostgreSQL (Psycopg 3) — único módulo con SQL
│   ├── auth.py                # validación, bcrypt, tokens de confirmación y sesión (sin Flask ni SQL)
│   ├── passwords.py           # hash/verificación bcrypt (mismo formato que el monolito)
│   ├── mailer.py              # envío SMTP hacia Postfix
│   ├── routes.py              # endpoints + errores XML/JSON
│   ├── serializers/           # xml_serializer.py · json_serializer.py · negociación de ?format
│   └── docs.py                # OpenAPI 3 + Swagger UI (ejemplos XML generados por el serializador)
├── tests/                     # pytest: 91 unitarias + 4 de integración con PostgreSQL
├── postman/                   # colección con pruebas automáticas
└── requirements.txt / requirements-dev.txt / .env.example
```

La base de datos **no** se modifica desde este directorio: los cambios viven en
[`../../data/`](../../data/README.md) (`schema.sql` y `migrations/`).

## 1. Requisitos previos

- Linux (CentOS/RHEL, Debian/Ubuntu…) o Windows; Python 3.10 o superior con `venv` y `pip`.
- PostgreSQL 13+ con la base `library_db` ya creada y poblada (esquema de `data/schema.sql`).
- Usuario `postgres` (o superusuario) para crear el rol, y `library_user` (dueño de las tablas).
- **Postfix** instalado y activo en la instancia (sección 5) si vas a enviar correos de confirmación.

```bash
# CentOS / RHEL
sudo dnf install -y python3 python3-pip
# Debian / Ubuntu
sudo apt install -y python3 python3-venv python3-pip
python3 --version   # >= 3.10
```

## 2. Instalación

```bash
cd services/login
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt      # Flask, Psycopg 3, bcrypt, flask-cors, email-validator, swagger-ui, gunicorn
```

## 3. Base de datos (una sola vez)

Ver [`data/README.md`](../../data/README.md) para el detalle y el impacto. Desde la raíz del monorepo:

```bash
# 3.1 Respaldo previo (books, Electron y monolito comparten esta BD)
pg_dump -h localhost -U library_user library_db > respaldo_antes_de_login.sql

# 3.2 Rol del servicio (contraseña por variable: no vive en el repo)
sudo -u postgres psql -d library_db -v login_password='UNA-CLAVE-LARGA' -f data/migrations/000_create_login_role.sql

# 3.3 Tablas y columnas (aditivo e idempotente; una transacción por archivo)
export PGPASSWORD=<clave-de-library_user>
psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/001_login_service.sql
psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/002_login_email_verification.sql

# 3.4 Permisos mínimos (siempre al final)
psql -h localhost -U library_user -d library_db -v ON_ERROR_STOP=1 -f data/migrations/003_login_service_grants.sql
```

Qué agrega: en `users`, 3 columnas *nullable* (`nombre`, `apellido_paterno`, `apellido_materno`) y
`email_verified_at`; un índice único sobre `lower(email)`; y las tablas `login_sessions` y `email_verifications`.
**No** altera nada existente. Las cuentas que ya existen (administrador y usuarios del monolito) quedan como
*verificadas*. La contraseña se guarda solo como `users.password_hash` (bcrypt); no hay tabla de contraseñas.
Instalación en una BD nueva: `psql -f data/schema.sql` ya lo incluye todo.

## 4. Variables de entorno

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # pega el resultado en FLASK_SECRET_KEY
```

| Variable | Por defecto | Descripción |
|---|---|---|
| `FLASK_SECRET_KEY` | — (obligatoria, ≥16) | Firma de la cookie de sesión. El servicio **no arranca** sin ella. |
| `DATABASE_URL` | — (obligatoria) | `postgresql://login_service_user:CLAVE@localhost:5432/library_db` |
| `FLASK_HOST` / `FLASK_PORT` | `127.0.0.1` / `5000` | Usa `0.0.0.0` para recibir tráfico de otras máquinas. |
| `EMAIL_CONFIRMATION_REQUIRED` | `true` | `false` = sin correo: las cuentas nuevas entran directo (solo desarrollo). |
| `MAIL_FROM` | — (obligatoria si lo anterior es `true`) | Remitente, p. ej. `Library <no-reply@tu-dominio.com>`. |
| `PUBLIC_BASE_URL` | `http://localhost:5000` | Base del enlace del correo. Debe abrirse desde el navegador del usuario (IP/dominio público de la VM). |
| `SMTP_HOST` / `SMTP_PORT` | `localhost` / `25` | Postfix local. Sin autenticación ni TLS (loopback). |
| `SMTP_STARTTLS` / `SMTP_USERNAME` / `SMTP_PASSWORD` | `false` / vacío | Solo si se usa un SMTP remoto en vez de Postfix. |
| `EMAIL_TOKEN_TTL_HOURS` | `24` | Vigencia del enlace de confirmación. |
| `RESEND_COOLDOWN_SECONDS` | `60` | Mínimo entre correos a una misma cuenta (evita inundar un buzón). |
| `SESSION_TIMEOUT_MINUTES` | `30` | Duración de la sesión. |
| `SESSION_COOKIE_SECURE` | `false` | Ponlo en `true` detrás de HTTPS. |
| `BCRYPT_ROUNDS` | `12` | Costo de bcrypt (igual que el monolito). |
| `EMAIL_CHECK_DELIVERABILITY` | `false` | `true` = además de validar el formato, consulta el DNS (MX) del dominio. |
| `CORS_ORIGINS` | vacío | Orígenes permitidos, separados por coma (con credenciales). |

`.env` está en `.gitignore`: nunca lo subas.

## 5. Correo con Postfix (`postfix.service`)

El servicio entrega el mensaje por SMTP a `localhost:25`; **Postfix** lo pone en cola y lo entrega/reenvía.
Si Postfix está caído, `POST /register` igual crea la cuenta y responde `"verification_email": "failed"`
(el usuario pide otro enlace con `POST /resend-verification` cuando Postfix vuelva).

```bash
# CentOS / RHEL
sudo dnf install -y postfix cyrus-sasl-plain s-nail
sudo systemctl enable --now postfix.service
systemctl status postfix.service --no-pager

# Solo escucha en loopback: NO debe ser un relay abierto
sudo postconf -e 'inet_interfaces = loopback-only'
sudo postconf -e 'inet_protocols = ipv4'
sudo postconf -e "myhostname = $(hostname -f)"
sudo systemctl reload postfix.service
ss -ltnp | grep ':25 '            # debe mostrar solo 127.0.0.1:25
```

**Cómo sale el correo hacia Gmail.** Hay dos caminos:

- **Directo** (Postfix habla con el MX de Gmail por el puerto 25): **en Google Cloud (Compute Engine) el tráfico
  saliente al puerto 25 está bloqueado**, y además una IP de VM sin SPF/DKIM/PTR termina en spam o rechazada.
  No lo uses en la VM.
- **Relay por el puerto 587** (recomendado): Postfix reenvía a un servidor SMTP autenticado. Ejemplo con el SMTP
  de Gmail y una *contraseña de aplicación* (requiere verificación en dos pasos; es SMTP, no POP/IMAP):

```bash
sudo postconf -e 'relayhost = [smtp.gmail.com]:587'
sudo postconf -e 'smtp_sasl_auth_enable = yes'
sudo postconf -e 'smtp_sasl_security_options = noanonymous'
sudo postconf -e 'smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd'
sudo postconf -e 'smtp_tls_security_level = encrypt'
sudo postconf -e 'smtp_tls_CAfile = /etc/pki/tls/certs/ca-bundle.crt'
echo '[smtp.gmail.com]:587 tu_cuenta@gmail.com:CONTRASENA_DE_APLICACION' | sudo tee /etc/postfix/sasl_passwd >/dev/null
sudo chmod 600 /etc/postfix/sasl_passwd && sudo postmap /etc/postfix/sasl_passwd
sudo systemctl restart postfix.service
```

Gmail reescribe el remitente a la cuenta autenticada: usa esa misma dirección en `MAIL_FROM`
(y respeta su límite diario de envíos). Cualquier otro relay SMTP (SendGrid, Mailgun, SES…) se configura igual
cambiando `relayhost` y las credenciales.

**Probar Postfix antes que la app:**

```bash
echo "prueba" | mail -s "prueba postfix" tu_cuenta@gmail.com     # llega a tu bandeja (revisa spam)
sudo postqueue -p                                                # cola: vacía = ya se entregó
sudo journalctl -u postfix.service -n 50 --no-pager              # o /var/log/maillog; busca status=sent
```

Configuración de la app para Postfix local (`.env`):

```dotenv
EMAIL_CONFIRMATION_REQUIRED=true
SMTP_HOST=localhost
SMTP_PORT=25
MAIL_FROM=Library <tu_cuenta@gmail.com>
PUBLIC_BASE_URL=http://IP-PUBLICA-DE-LA-VM:5000     # el enlace se abre desde el navegador del usuario
```

> Nota: el puerto 5000 debe ser alcanzable desde el navegador de quien recibe el correo (regla de firewall
> restringida a las IP que necesites, o un dominio con proxy inverso). Si no, el enlace no abrirá.

## 6. Ejecución (puerto 5000)

```bash
# Desarrollo
python app.py                                   # http://127.0.0.1:5000

# Despliegue (Linux)
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

Servicio systemd (`/etc/systemd/system/login.service`, ajusta rutas y usuario). Depende de `postfix.service`
con `Wants=` (blando): si Postfix falla, el login sigue funcionando y solo el envío del correo se degrada.

```ini
[Unit]
Description=Library login service
After=network.target postgresql.service postfix.service
Wants=postfix.service

[Service]
User=ruth
WorkingDirectory=/opt/app/services/login
EnvironmentFile=/opt/app/services/login/.env
ExecStart=/opt/app/services/login/.venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now login && curl -s localhost:5000/health
```

Comprueba que el 5000 no esté ya ocupado (`ss -ltnp | grep :5000`): la documentación de soap también lo usa por defecto.

## 7. Endpoints

Todos aceptan `?format=xml` (por defecto) o `?format=json`; otro valor → `400 invalid_format`.
Los cuerpos `POST` se envían como JSON (UTF-8).

| Método | Ruta | Función | Códigos |
|---|---|---|---|
| POST | `/register` | Registra al usuario y envía el correo de confirmación | 201 · 400 · 409 |
| GET | `/verify/<token>` | Confirma el correo (es el enlace del mensaje) | 200 · 404 · 410 |
| POST | `/resend-verification` | Reenvía el enlace (máx. uno por minuto) | 202 · 400 |
| POST | `/login` | Verifica credenciales e inicia sesión (30 min) | 200 · 400 · 401 · 403 |
| POST | `/logout` | Revoca la sesión | 200 · 401 |
| GET | `/session` | Usuario autenticado y tiempo restante | 200 · 401 |
| GET | `/health` | Servicio + PostgreSQL + esquema | 200 · 503 |
| GET | `/docs/` · `/openapi.json` | Swagger UI / especificación | 200 |

**Registro** pide `nombre`, `apellido_paterno`, `apellido_materno`, `email`, `password` (≥ 8 caracteres,
≤ 72 bytes por el límite de bcrypt). El correo se valida (formato) antes de registrar y es único sin
distinguir mayúsculas. La cuenta nueva nunca es administradora.

### Flujo de confirmación

1. `POST /register` → `201`, cuenta con `email_verified: false`, y el campo `verification_email`:
   `sent` (Postfix aceptó el mensaje), `failed` (Postfix caído: usa `/resend-verification`) o `not_required`.
2. El usuario recibe un correo corto con un botón **"Da clic aquí para confirmar tu cuenta"** (enlace
   `PUBLIC_BASE_URL/verify/<token>`); el mismo token también viene escrito en el correo para poder probar a mano.
3. `POST /login` antes de confirmar → `403 email_not_confirmed` (solo si la contraseña es correcta).
4. Al abrir el enlace, el navegador muestra la respuesta XML (`Cuenta confirmada correctamente…`, `status: confirmed`).
   Abrirlo otra vez (p. ej. un escáner de enlaces de Gmail) devuelve `already_confirmed`, sin error.
5. Enlace vencido (24 h) → `410 token_expired`; se pide otro con `POST /resend-verification`.

El token es aleatorio (256 bits), de un solo uso lógico, y **en la base solo se guarda su SHA-256**.
`/resend-verification` responde `202` igual exista o no el correo (no revela qué cuentas existen).

### Ejemplos con curl

```bash
B=http://localhost:5000

curl -s $B/health                            # XML por defecto
curl -s "$B/health?format=json"              # JSON

# registro (XML por defecto) → recibe el correo con el enlace
curl -s -X POST $B/register -H 'Content-Type: application/json' \
  -d '{"nombre":"Ana","apellido_paterno":"López","apellido_materno":"Díaz","email":"ana@gmail.com","password":"ClaveSegura123"}'

# abrir el enlace del correo (lo mismo que hace el navegador)
curl -s "$B/verify/TOKEN_DEL_CORREO"

# login guardando la cookie de sesión (-c) y reutilizándola (-b)
curl -s -c cookies.txt -X POST "$B/login?format=json" -H 'Content-Type: application/json' \
  -d '{"email":"ana@gmail.com","password":"ClaveSegura123"}'
curl -s -b cookies.txt $B/session                       # XML
curl -s -b cookies.txt "$B/session?format=json"         # JSON
curl -s -b cookies.txt -X POST "$B/logout?format=json"

# reenviar el enlace
curl -s -X POST "$B/resend-verification?format=json" -H 'Content-Type: application/json' -d '{"email":"ana@gmail.com"}'
```

> En la consola de Windows los acentos pueden enviarse en otra codificación y el servicio responderá
> `400 invalid_body`. Usa `--data-binary @archivo.json` guardado en UTF-8, o Postman.

### Respuestas

XML (por defecto) — `POST /register`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<response>
  <message>Usuario registrado. Te enviamos un correo con un enlace de confirmación: ábrelo para activar la cuenta y después inicia sesión con POST /login.</message>
  <verification_email>sent</verification_email>
  <user>
    <id>6</id><nombre>Ruth</nombre><apellido_paterno>Soriano</apellido_paterno>
    <apellido_materno>López</apellido_materno><display_name>Ruth Soriano López</display_name>
    <email>ruth.test@gmail.com</email><email_verified>false</email_verified>
    <created_at>2026-09-18T21:38:29+00:00</created_at>
  </user>
</response>
```

Al abrir el enlace — `GET /verify/<token>`:

```xml
<response>
  <message>Cuenta confirmada correctamente. Ya puedes iniciar sesión con POST /login.</message>
  <status>confirmed</status>
  <user>… <email_verified>true</email_verified> …</user>
</response>
```

JSON — `GET /session?format=json`:

```json
{ "authenticated": true,
  "user": { "id": 6, "email": "ruth.test@gmail.com", "display_name": "Ruth Soriano López", "email_verified": true, "...": "..." },
  "session": { "expires_at": "2026-09-18T21:41:58+00:00", "expires_in_seconds": 1799 } }
```

Errores (mismo formato pedido): `{"error": {"code": "...", "message": "...", "details": [...]}}`. Códigos:
`validation_error`, `invalid_body`, `invalid_format`, `email_exists`, `invalid_credentials`, `email_not_confirmed`,
`account_disabled`, `invalid_token`, `token_expired`, `not_authenticated`, `session_expired`,
`database_unavailable`, `schema_missing`, `internal_error`.

### Sesiones de 30 minutos

`/login` crea una fila en `login_sessions` (`expires_at = ahora + 30 min`) y guarda su id en la cookie
firmada de Flask (`login_session`, HttpOnly). Pasados los 30 minutos, `GET /session` responde
**401** con `error.code = session_expired` (en XML o JSON según `?format`) hasta que se vuelva a iniciar
sesión; `/logout` revoca la sesión en la BD, así que una cookie copiada deja de servir.

Para probar la caducidad sin esperar: arranca con `SESSION_TIMEOUT_MINUTES=1`, o fuerza el vencimiento en la BD
(como `library_user`; el rol del servicio no puede hacer este `UPDATE`):

```sql
UPDATE login_sessions SET created_at = now() - interval '31 minutes', expires_at = now() - interval '1 minute'
 WHERE revoked_at IS NULL;
```

### Cuentas del monolito

Usan la misma tabla `users` y el mismo bcrypt: el administrador creado con `create-admin.js` y los usuarios del
CRUD del monolito ya cuentan como verificados y pueden iniciar sesión aquí (con `nombre`/apellidos en `null` y
`display_name` con su nombre). Las cuentas registradas aquí sirven en el monolito.

## 8. Pruebas

```bash
pip install -r requirements-dev.txt
pytest -q                          # 91 unitarias (repositorio en memoria, reloj y correo simulados)

# Integración contra PostgreSQL (BD DESECHABLE, no la de producción):
export TEST_DATABASE_URL='postgresql://login_service_user:CLAVE@localhost:5432/library_db'
export TEST_ADMIN_DATABASE_URL='postgresql://library_user:<clave>@localhost:5432/library_db'
pytest -q tests/test_postgres_integration.py
```

**Postman**: importa `postman/login-service.postman_collection.json` y ajusta `base_url`
(y `email_domain=gmail.com` si quieres que el correo llegue a una bandeja real).

1. Ejecuta las carpetas **1 y 2** (Health y Registro). El registro dispara el correo por Postfix.
2. Abre el correo en Gmail y haz clic en **"Da clic aquí para confirmar tu cuenta"** (verás la respuesta XML), o
   copia el token que viene en el correo (debajo del botón) en la variable de colección `verify_token`.
3. Ejecuta las carpetas **3 y 4** (Confirmación y Login/sesión/logout). La 3 acepta `confirmed` o `already_confirmed`.
4. La carpeta **5** es la prueba manual de caducidad de 30 minutos.

Por consola: `newman run postman/login-service.postman_collection.json --env-var base_url=http://localhost:5000`.
(Si defines `mailpit_url`, la colección lee el token de un buzón de pruebas Mailpit — útil solo en desarrollo.)

## 9. Seguridad y decisiones

- Contraseñas: bcrypt (cost 12), nunca en texto plano ni en logs ni en respuestas. Login con tiempo
  parecido exista o no el correo; mensaje idéntico para "correo inexistente" y "contraseña mala".
- Tokens de confirmación: 256 bits aleatorios, solo su SHA-256 en la BD, vigencia de 24 h, reenvío con
  enfriamiento de 60 s. Las cabeceras del correo se construyen con `EmailMessage` (sin inyección de cabeceras).
- El rol `login_service_user` solo puede `SELECT`/`INSERT` en columnas concretas de `users`, `UPDATE` de
  `email_verified_at`, y operar sobre `login_sessions` y `email_verifications`. **No** puede crear
  administradores, borrar, ni leer books/catálogo (verificado).
- Cookie `HttpOnly`, `SameSite=Lax`; respuestas con `Cache-Control: no-store`; los errores nunca filtran detalles internos.
- **No implementado (extensiones futuras)**: captcha, límite de intentos de login (rate limiting), JWT y Redis.
  La estructura (`auth.py` sin dependencias de Flask/SQL, `repository.py` y `mailer.py` aislados) permite añadirlos
  sin reescribir los endpoints.
- Sin borrado de filas vencidas: `login_sessions` y `email_verifications` crecen; programa una limpieza periódica
  como `library_user` si el volumen lo requiere.

## 10. Problemas frecuentes

| Síntoma | Causa / solución |
|---|---|
| `Error de configuración: FLASK_SECRET_KEY falta…` / `MAIL_FROM es obligatorio…` | Falta `.env` o esa variable. Sin correo (solo desarrollo): `EMAIL_CONFIRMATION_REQUIRED=false`. |
| `POST /register` → `"verification_email": "failed"` | Postfix caído o no escucha en `localhost:25` (`systemctl status postfix.service`, `ss -ltnp \| grep :25`). Revisa el log de la app: `No se pudo entregar el correo…`. Al volver Postfix, `POST /resend-verification`. |
| El correo no llega a Gmail | `sudo postqueue -p` y `journalctl -u postfix.service`. En Google Cloud el puerto 25 saliente está bloqueado: usa relay por 587 (sección 5). Revisa spam. |
| El enlace del correo no abre | `PUBLIC_BASE_URL` apunta a `localhost`/IP privada, o el puerto 5000 no está abierto para tu navegador. |
| `/login` → `403 email_not_confirmed` | Abre el enlace del correo o pide otro con `/resend-verification` (espera 60 s entre envíos). |
| `/health` → `503 database_unavailable` | PostgreSQL caído, `DATABASE_URL` incorrecta o `pg_hba.conf` no permite la conexión. |
| `/health` → `503 schema_missing` | Faltan las migraciones `001` y `002` (ver sección 3). |
| `permission denied for table …` | Falta `003_login_service_grants.sql`. |
| `Address already in use` en 5000 | Otro proceso usa el puerto: `ss -ltnp \| grep :5000`. |
| `400 invalid_body` con acentos | Cuerpo no UTF-8 (ver nota de curl en Windows). |
