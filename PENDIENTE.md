# PENDIENTE — traspaso para continuar el código

Estado al 2026-10-06. Proyecto Library: 6 microservicios Flask (login 5000, books/soap 5001, users 5002, authors 5003,
pedidos 5004, pagos 5005) + PostgreSQL (`library_db`, fuente de verdad) + Redis (sesiones, refresh, revocación de JWT,
caché, candados, idempotencia). Diseño completo en [`docs/REDIS_Y_JWT.md`](docs/REDIS_Y_JWT.md).

## Hecho y probado localmente
- Paquete común `services/shared/library_common` (JWT, Redis, errores, métricas, config, pg): 96 tests.
- login (JWT 20 min con `jti`, refresh con rotación, logout que revoca): 133 tests + 5 de integración con PostgreSQL.
- books: caché Redis + JWT con roles admin/staff en escrituras: 67 tests.
- users, authors, pedidos, pagos: código, funciones SQL `SECURITY DEFINER`, tests (los de PostgreSQL real exigen `TEST_DATABASE_URL`).
- Migraciones `data/migrations/006`–`011` (+ rollbacks `991`–`996`), verificadas con `data/tests/verify_microservices_db.sql` (79 checks).
- Escenario de punta a punta en Docker (`bash e2e/run_local.sh`): fases A normal, B Redis caído, C recuperación → "E2E COMPLETO: OK".

## NO se ha ejecutado en la VM (`maquina-02`) — lo hace la persona dueña, con sus contraseñas
1. `git pull` en `/opt/auth`.
2. `bash deploy/setup_microservices_vm.sh` (idempotente: pide contraseñas de `postgres` y `library_user`, hace backup, corre
   migraciones 006–011, configura Redis con `requirepass`/AOF/`maxmemory`, crea venvs, `.env` con el mismo `JWT_SECRET_KEY`
   y `REDIS_URL`, units systemd y nginx, y comprueba `/health`). Solo se validó con `bash -n` y su bloque de Redis contra un contenedor.
3. `bash deploy/evidencias_microservicios.sh` (corre el escenario real, apaga/enciende Redis con systemctl y revisa que los logs no filtren tokens).
4. Capturar la evidencia y la reflexión que pide el profesor.

## Pendiente de código / documentación
- [x] README propio de `services/users`, `authors`, `pedidos`, `pagos` (endpoints, roles, variables de `.env.example`; la tabla de roles ya está en `docs/REDIS_Y_JWT.md`).
- [x] Actualizar `README.md` raíz (tabla de servicios: faltan puertos 5002–5005) y `deploy/README.md` (scripts nuevos, units, `nginx-microservices-proxy.conf`, e2e).
- [x] Actualizar `services/soap/README.md`: su sección «Autenticación JWT» documenta `library_common.JwtAuth` y `JWT_SECRET_KEY`, con caché `books:*`.
- [x] HTTPS: creado `deploy/setup_tls_vm.sh` (pendiente ejecutar en VM) (certificado autofirmado en nginx; sin dominio no hay Let's Encrypt). El firewall de GCP ya permite 443; abrirlo/cambiarlo lo decide el dueño.
- [x] Colecciones Postman de los servicios nuevos y actualizar la de login (`/token/refresh`, campos nuevos).
- [x] Configuración local de books migrada a gunicorn, producción y debug desactivado.
- [ ] Aplicar el despliegue y comprobar en la VM que books corre con la unit nueva (no validado remotamente).
- [x] Sincronizados los archivos del proyecto en `Desktop\app`, con respaldo de reemplazos en `.auth-sync-backups`; sin copiar .env, entornos ni proyectos ajenos. Script repetible: `deploy/sync_workspace.ps1`.
- [ ] La app Electron (`electron-catalog`) no usa JWT (solo hace GET públicos); no requiere cambios por ahora.

## Limitaciones conocidas
- Un cambio de rol o la desactivación de un usuario se aplica en el siguiente refresh/login (≤ 20 min) porque el rol viaja en el JWT.
- Redis caído ⇒ no hay login/refresh/logout ni rutas protegidas (503, falla cerrado); los `GET` públicos cacheados siguen vía PostgreSQL.
- Migración 011 (revocar `EXECUTE` a PUBLIC en las funciones `fn_*` de books/SOAP; cualquier rol de BD podía llamarlas) debe correrse como `postgres`.

## Reglas que no hay que romper
- Nunca poner `JWT_SECRET_KEY`, contraseñas ni tokens en el código, logs, commits ni chats. Los `.env` están en `.gitignore`.
- Cada servicio usa su propio rol de BD con solo `EXECUTE` de sus funciones; PostgreSQL manda, Redis nunca es fuente de verdad.
- Sesión, revocación, candados e idempotencia fallan cerrado; solo la caché de lecturas falla abierta.

## Comandos útiles
```bash
# tests por servicio (usar Python 3.12; bcrypt no compila en algunos Python locales)
cd services/shared && pip install -e . && pytest
cd services/login  && pip install -r requirements-dev.txt && pytest
cd services/soap   && pip install -r requirements-dev.txt && pytest
# todo el sistema en Docker (PostgreSQL + Redis + 6 servicios)
bash e2e/run_local.sh
```

## Continuación local

Se añadieron READMEs y colecciones de users/authors/pedidos/pagos, refresh en Postman login, documentación raíz/deploy y script TLS. Books usa gunicorn en la unit nueva. La ejecución en VM y su evidencia siguen pendientes. La copia externa conserva archivos antiguos y `auth-service` histórico; no elimina material del destino.

Validación de esta continuación: 67 tests de books pasaron con Python 3.12 en `.venv-check`; JSON de las cinco colecciones válido y rutas de los cuatro servicios contrastadas con el código. `bash -n` pasó para TLS y setup_microservices; `git diff --check` sin errores. TLS/nginx/systemd no se han ejecutado en la VM y no se volvió a ejecutar e2e Docker.
