# authors — Library (puerto 5003)

GET públicos. POST/PUT/PATCH/DELETE requieren admin o staff. Campos: first_name (obligatorio al crear/reemplazar), last_name y biography opcionales. Vincular libro: isbn y author_order opcional (1–99). Un autor vinculado a libros no se elimina (409). Caché authors:* de 60 s; las escrituras invalidan también books:*.

## Arranque local

Python 3.12, PostgreSQL con las migraciones 006–011 y Redis protegido. El rol `authors_service_user` tiene solo EXECUTE de sus funciones; no uses postgres para ejecutar el servicio.

```bash
cd services/authors
python -m venv .venv
source .venv/bin/activate  # Windows: .venv/Scripts/Activate.ps1
pip install ../shared
pip install -r requirements-dev.txt
cp .env.example .env
# Edita .env con tus valores locales antes de arrancar.
python app.py
```

Producción: unidad [`../../deploy/authors.service`](../../deploy/authors.service), gunicorn en loopback, detrás de nginx.

## Rutas y permisos

- `GET /authors`
- `GET /authors/<int:author_id>`
- `GET /authors/<int:author_id>/books`
- `POST /authors`
- `PUT /authors/<int:author_id>`
- `PATCH /authors/<int:author_id>`
- `DELETE /authors/<int:author_id>`
- `POST /authors/<int:author_id>/books`
- `DELETE /authors/<int:author_id>/books/<isbn>`
- `GET /health`: público, estado de PostgreSQL y Redis.
- `GET /metrics`: JWT de admin.

Las rutas anteriores son internas. Nginx elimina el prefijo `/authors/`: por ejemplo, `http://VM/authors/authors` llega a `/authors`. `base_url` de Postman termina en `/authors` al usar nginx, o usa `http://127.0.0.1:5003` directamente.

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

`DATABASE_URL` usa el rol propio. `JWT_SECRET_KEY` (mínimo 32 caracteres), `JWT_ISSUER` y `REDIS_URL` deben coincidir con login. Timeouts Redis en segundos; CACHE_TTL_SECONDS controla la caché de lectura. CORS_ORIGINS vacío desactiva CORS; configura solo tus orígenes. Nunca versiones .env, contraseñas ni tokens. [JWT, roles y política de fallo](../../docs/REDIS_Y_JWT.md).

## Pruebas

```bash
pytest
# Integración con PostgreSQL real: configura TEST_DATABASE_URL en tu entorno.
# Sistema completo (desde la raíz): bash e2e/run_local.sh
```

Importa [`postman/authors-service.postman_collection.json`](postman/authors-service.postman_collection.json). Ajusta variables e IDs y pega un JWT de login en la variable local token. Ejecuta escrituras solo sobre datos de prueba; no uses el Runner indiscriminadamente en la VM.
