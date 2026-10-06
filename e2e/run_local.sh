#!/bin/bash
# Prueba de punta a punta LOCAL: 6 servicios + PostgreSQL real + Redis real (Docker), con la caída de Redis incluida.
#
#   Requisitos: Docker corriendo y un PostgreSQL con el esquema y las migraciones 006-011 (p. ej. el contenedor de
#   pruebas de data/tests/verify_microservices_db.sql) publicado en PG_PORT, con los roles de servicio creados.
#
#   PG_PORT=55432 bash e2e/run_local.sh
set -u
cd "$(dirname "$0")/.."
PG_PORT=${PG_PORT:-55432}
REDIS_PORT=${REDIS_PORT:-56379}
JWT=$(python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || python -c 'import secrets; print(secrets.token_hex(32))')
RPW=$(python3 -c 'import secrets; print(secrets.token_hex(16))' 2>/dev/null || python -c 'import secrets; print(secrets.token_hex(16))')
ROOT_WIN=$(cd services && pwd -W 2>/dev/null || pwd)
E2E_WIN=$(cd e2e && pwd -W 2>/dev/null || pwd)
export MSYS_NO_PATHCONV=1

echo "== construyendo imagen"; docker build -q -t lib-e2e e2e >/dev/null || exit 1
docker rm -f lib_redis_e2e lib_e2e_app >/dev/null 2>&1
echo "== Redis real (requirepass + AOF, como en la VM)"
docker run -d --name lib_redis_e2e -p "$REDIS_PORT:6379" redis:7-alpine redis-server --requirepass "$RPW" --appendonly yes >/dev/null || exit 1
sleep 1

PGH="host.docker.internal:$PG_PORT"
echo "== arrancando los 6 servicios"
docker run -d --name lib_e2e_app -v "$ROOT_WIN:/work" -v "$E2E_WIN:/e2e" \
  -e PGHOST_PORT="$PGH" -e REDIS_URL="redis://:$RPW@host.docker.internal:$REDIS_PORT/0" -e JWT_SECRET_KEY="$JWT" \
  -e PW_login=logintest -e PW_soap=soaptest -e PW_users=u1 -e PW_authors=a1 -e PW_pedidos=p1 -e PW_pagos=g1 \
  -e ADMIN_DSN="postgresql://library_user:libtest@$PGH/library_db" lib-e2e sleep infinity >/dev/null || exit 1
docker exec lib_e2e_app bash /e2e/start_services.sh || { docker logs lib_e2e_app | tail; exit 1; }

phase(){ docker exec lib_e2e_app python /e2e/e2e_scenario.py "$1"; }
rc=0
echo; echo "################ FASE A: flujo normal ################";            phase A || rc=1
echo; echo "################ FASE B: REDIS CAÍDO (docker stop) ################"; docker stop lib_redis_e2e >/dev/null; phase B || rc=1
echo; echo "################ FASE C: Redis de vuelta ################";         docker start lib_redis_e2e >/dev/null; sleep 2; phase C || rc=1

echo; echo "== ¿se coló algún token o contraseña en los logs de los servicios?"
if docker exec lib_e2e_app sh -c "grep -l -E 'eyJ[A-Za-z0-9_-]{10,}|$RPW|$JWT' /tmp/*.log" 2>/dev/null; then echo "  ✘ SÍ: revisa los archivos de arriba"; rc=1; else echo "  ✔ no: ni JWT, ni JWT_SECRET_KEY, ni contraseña de Redis aparecen en los logs"; fi

docker rm -f lib_e2e_app lib_redis_e2e >/dev/null 2>&1
[ $rc = 0 ] && echo "E2E COMPLETO: OK" || echo "E2E CON FALLAS"
exit $rc
