#!/bin/bash
# Levanta LOCALMENTE los 6 microservicios + Redis (Docker) y deja los puertos publicados en tu equipo, para usar
# el cliente de escritorio Python Tk (o Postman/curl) sin necesitar la VM.
#
#   PG_PORT=55432 bash e2e/serve_local.sh          # arranca y se queda corriendo
#   bash e2e/serve_local.sh stop                   # lo detiene y borra los contenedores
#   docker stop lib_redis_local                    # (con todo arriba) simula la caída de Redis
#
# Requisitos: Docker y un PostgreSQL con el esquema + migraciones 006-011 y los roles de servicio (el mismo contenedor
# de pruebas que usa e2e/run_local.sh) publicado en PG_PORT.
# Puertos en tu equipo (BASE_PORT=15000 por defecto): login 15000, books 15001, users 15002, authors 15003,
# pedidos 15004, pagos 15005. En la app Tk: Configuración -> «Usar localhost» y cambia el puerto, o pon las URLs a mano.
# La contraseña de los usuarios demo (admin/staff/customer) se genera al azar y se imprime UNA vez en esta terminal
# (o se guarda en el archivo DEMO_PW_FILE si lo defines, sin imprimirla).
set -u
cd "$(dirname "$0")/.."
if [ "${1:-}" = "stop" ]; then docker rm -f lib_redis_local lib_serve_app >/dev/null 2>&1; echo "detenido"; exit 0; fi

PG_PORT=${PG_PORT:-55432}
REDIS_PORT=${REDIS_PORT:-56380}
BASE_PORT=${BASE_PORT:-15000}
py() { python3 "$@" 2>/dev/null || python "$@"; }
JWT=$(py -c 'import secrets; print(secrets.token_hex(32))')
RPW=$(py -c 'import secrets; print(secrets.token_hex(16))')
DEMO_PW=$(py -c 'import secrets; print(secrets.token_urlsafe(12))')
ROOT_WIN=$(cd services && pwd -W 2>/dev/null || pwd)
E2E_WIN=$(cd e2e && pwd -W 2>/dev/null || pwd)
export MSYS_NO_PATHCONV=1

echo "== construyendo imagen"; docker build -q -t lib-e2e e2e >/dev/null || exit 1
docker rm -f lib_redis_local lib_serve_app >/dev/null 2>&1
docker run -d --name lib_redis_local -p "$REDIS_PORT:6379" redis:7-alpine redis-server --requirepass "$RPW" --appendonly yes >/dev/null || exit 1
sleep 1
PGH="host.docker.internal:$PG_PORT"
PORTS=""; for i in 0 1 2 3 4 5; do PORTS="$PORTS -p $((BASE_PORT + i)):$((5000 + i))"; done
docker run -d --name lib_serve_app $PORTS -v "$ROOT_WIN:/work" -v "$E2E_WIN:/e2e" \
  -e BIND=0.0.0.0 -e PGHOST_PORT="$PGH" -e REDIS_URL="redis://:$RPW@host.docker.internal:$REDIS_PORT/0" -e JWT_SECRET_KEY="$JWT" \
  -e PW_login=logintest -e PW_soap=soaptest -e PW_users=u1 -e PW_authors=a1 -e PW_pedidos=p1 -e PW_pagos=g1 \
  -e DEMO_PASSWORD="$DEMO_PW" -e ADMIN_DSN="postgresql://library_user:libtest@$PGH/library_db" \
  lib-e2e sleep infinity >/dev/null || exit 1
docker exec lib_serve_app bash /e2e/start_services.sh || { docker logs lib_serve_app | tail; exit 1; }
docker exec lib_serve_app python /e2e/seed_demo_users.py || exit 1

echo
echo "Listo. Servicios en tu equipo:"
for name in login:0 books:1 users:2 authors:3 pedidos:4 pagos:5; do printf "  %-8s http://localhost:%s\n" "${name%%:*}" "$((BASE_PORT + ${name##*:}))"; done
echo "Usuarios demo (misma contraseña): demo-admin@example.com · demo-staff@example.com · demo-customer@example.com"
if [ -n "${DEMO_PW_FILE:-}" ]; then printf %s "$DEMO_PW" > "$DEMO_PW_FILE"; echo "Contraseña demo guardada en $DEMO_PW_FILE"
else echo "Contraseña demo (solo se muestra ahora): $DEMO_PW"; fi
echo "Para detener: bash e2e/serve_local.sh stop"
