# auth — Library

Monorepo de seis microservicios Flask con PostgreSQL (`library_db`, fuente de verdad), Redis para sesiones, revocación JWT, caché, candados e idempotencia, y Electron para consultar el catálogo.

## Servicios

- [login](services/login/README.md): 5000, prefijo nginx `/auth/`.
- [books / SOAP](services/soap/README.md): 5001, prefijo `/soap/`.
- [users](services/users/README.md): 5002, prefijo `/users/`.
- [authors](services/authors/README.md): 5003, prefijo `/authors/`.
- [pedidos](services/pedidos/README.md): 5004, prefijo `/pedidos/`.
- [pagos](services/pagos/README.md): 5005, prefijo `/pagos/`.

Los prefijos describen el proxy previsto; verifica su instalación en la VM. Nginx elimina el prefijo: `/users/users/me` llega a `/users/me`. Todos los servicios escuchan en loopback; el monolito externo continúa en 3000 bajo `/library/`.

## Configuración y seguridad

Instala `services/shared` en cada entorno virtual y configura el `.env` de cada servicio a partir de su `.env.example`. Usa el mismo `JWT_SECRET_KEY` y Redis protegido en los seis; cada servicio tiene su propio rol PostgreSQL con EXECUTE de sus funciones. Nunca versiones secretos. [Diseño JWT/Redis y permisos](docs/REDIS_Y_JWT.md).

Books y authors admiten lecturas públicas; sus escrituras exigen admin/staff. Los demás recursos privados requieren JWT. Si Redis falla, autenticación y rutas protegidas devuelven 503; las lecturas públicas siguen por PostgreSQL.

## Desarrollo, pruebas y despliegue

- [Base de datos y migraciones](data/README.md).
- [Despliegue CentOS, TLS y evidencia](deploy/README.md).
- [Pendientes y estado de validación](PENDIENTE.md).
- [Electron](electron-catalog/README.md): consume GET públicos; configura la URL `/soap/books` y la base de imágenes `/library`.
- Colecciones Postman en `services/<servicio>/postman/`; configura variables locales y usa datos de prueba.

```bash
# Desde la carpeta de un servicio, con su venv activo:
pip install ../shared
pip install -r requirements-dev.txt
pytest
# Desde la raíz, con Docker disponible:
bash e2e/run_local.sh
```

Los tests con PostgreSQL real requieren `TEST_DATABASE_URL`. La IP externa de la VM puede cambiar al reiniciar. `entrega_fraude/` y la transcripción son ajenos a este trabajo.
