# pagos — Library (puerto 5005)

Todas las rutas requieren JWT. Customer paga/consulta solo sus pedidos; staff/admin pueden operar sobre todos. POST exige order_id, method (tarjeta, transferencia o efectivo), amount positivo con máximo dos decimales, e Idempotency-Key (1–64 caracteres: letras, números, . _ : -). Reintenta el mismo pago con la misma clave y cuerpo; otro cuerpo con esa clave da 409. El pago y el estado pagado se registran en una transacción; Redis y UNIQUE en PostgreSQL evitan duplicados. PUT/PATCH/DELETE con JWT responden 405. No integra una pasarela bancaria.

## Arranque local

Python 3.12, PostgreSQL con las migraciones 006–011 y Redis protegido. El rol `pagos_service_user` tiene solo EXECUTE de sus funciones; no uses postgres para ejecutar el servicio.

```bash
cd services/pagos
python -m venv .venv
source .venv/bin/activate  # Windows: .venv/Scripts/Activate.ps1
pip install ../shared
pip install -r requirements-dev.txt
cp .env.example .env
# Edita .env con tus valores locales antes de arrancar.
python app.py
```

Producción: unidad [`../../deploy/pagos.service`](../../deploy/pagos.service), gunicorn en loopback, detrás de nginx.

## Rutas y permisos

- `POST /pagos`
- `GET /pagos`
- `GET /pagos/<int:payment_id>`
- `PUT/PATCH/DELETE /pagos/<payment_id>` (inmutables: 405 con JWT).
- `GET /health`: público, estado de PostgreSQL y Redis.
- `GET /metrics`: JWT de admin.

Las rutas anteriores son internas. Nginx elimina el prefijo `/pagos/`: por ejemplo, `http://VM/pagos/pagos` llega a `/pagos`. `base_url` de Postman termina en `/pagos` al usar nginx, o usa `http://127.0.0.1:5005` directamente.

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

Importa [`postman/pagos-service.postman_collection.json`](postman/pagos-service.postman_collection.json). Ajusta variables e IDs y pega un JWT de login en la variable local token. Ejecuta escrituras solo sobre datos de prueba; no uses el Runner indiscriminadamente en la VM.
