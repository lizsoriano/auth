# users — Library (puerto 5002)

Admin lista, crea, reemplaza y elimina usuarios. Cada usuario consulta y modifica su propia cuenta; solo admin cambia role_id/is_active. GET /roles requiere JWT. PUT de perfil exige email, display_name, nombre, apellido_paterno, apellido_materno, role_id e is_active. Cambio de contraseña: password y current_password (esta última obligatoria salvo admin). No se permite borrar la propia cuenta.

## Arranque local

Python 3.12, PostgreSQL con las migraciones 006–011 y Redis protegido. El rol `users_service_user` tiene solo EXECUTE de sus funciones; no uses postgres para ejecutar el servicio.

```bash
cd services/users
python -m venv .venv
source .venv/bin/activate  # Windows: .venv/Scripts/Activate.ps1
pip install ../shared
pip install -r requirements-dev.txt
cp .env.example .env
# Edita .env con tus valores locales antes de arrancar.
python app.py
```

Producción: unidad [`../../deploy/users.service`](../../deploy/users.service), gunicorn en loopback, detrás de nginx.

## Rutas y permisos

- `GET /roles`
- `GET /users`
- `GET /users/me`
- `GET /users/<int:user_id>`
- `POST /users`
- `PATCH /users/<int:user_id>`
- `PUT /users/<int:user_id>`
- `PUT /users/<int:user_id>/password`
- `DELETE /users/<int:user_id>`
- `GET /health`: público, estado de PostgreSQL y Redis.
- `GET /metrics`: JWT de admin.

Las rutas anteriores son internas. Nginx elimina el prefijo `/users/`: por ejemplo, `http://VM/users/users` llega a `/users`. `base_url` de Postman termina en `/users` al usar nginx, o usa `http://127.0.0.1:5002` directamente.

Entradas JSON (`Content-Type: application/json`). Respuestas XML por defecto; usa `?format=json` para JSON. Listas admiten limit/offset. JWT en `Authorization: Bearer <token>`: 401 inválido/revocado, 403 rol insuficiente; 404 puede ocultar recursos ajenos. Redis caído devuelve 503 en rutas protegidas; las lecturas públicas de authors siguen por PostgreSQL.

## Variables

La descripción y los valores de referencia están en [`.env.example`](.env.example):

- `FLASK_HOST`
- `FLASK_PORT`
- `LOG_LEVEL`
- `DATABASE_URL`
- `DB_CONNECT_TIMEOUT`
- `JWT_SECRET_KEY`
- `JWT_ISSUER`
- `REDIS_URL`
- `REDIS_CONNECT_TIMEOUT`
- `REDIS_SOCKET_TIMEOUT`
- `CACHE_TTL_SECONDS`
- `CORS_ORIGINS`
- `MIN_PASSWORD_LENGTH`
- `BCRYPT_ROUNDS`

`DATABASE_URL` usa el rol propio. `JWT_SECRET_KEY` (mínimo 32 caracteres), `JWT_ISSUER` y `REDIS_URL` deben coincidir con login. Timeouts Redis en segundos; CACHE_TTL_SECONDS controla la caché de lectura. CORS_ORIGINS vacío desactiva CORS; configura solo tus orígenes. Nunca versiones .env, contraseñas ni tokens. [JWT, roles y política de fallo](../../docs/REDIS_Y_JWT.md).

## Pruebas

```bash
pytest
# Integración con PostgreSQL real: configura TEST_DATABASE_URL en tu entorno.
# Sistema completo (desde la raíz): bash e2e/run_local.sh
```

Importa [`postman/users-service.postman_collection.json`](postman/users-service.postman_collection.json). Ajusta variables e IDs y pega un JWT de login en la variable local token. Ejecuta escrituras solo sobre datos de prueba; no uses el Runner indiscriminadamente en la VM.
