#!/bin/bash
# Dentro del contenedor: arranca los 6 servicios (python app.py) con su propio rol de BD y el MISMO JWT/Redis.
# Variables que debe traer el entorno: PGHOST_PORT (host:puerto de PostgreSQL), REDIS_URL, JWT_SECRET_KEY,
# y las contraseñas de los roles: PW_login PW_soap PW_users PW_authors PW_pedidos PW_pagos.
set -eu
DB=${DB:-library_db}
COMMON="JWT_SECRET_KEY=$JWT_SECRET_KEY REDIS_URL=$REDIS_URL CACHE_TTL_SECONDS=60 LOG_LEVEL=INFO FLASK_HOST=127.0.0.1"
run() { # run NOMBRE DIRECTORIO VARIABLES...
  local name=$1 dir=$2; shift 2
  (cd "/work/$dir" && env $COMMON "$@" python app.py > "/tmp/$name.log" 2>&1 &)
}
run login   login   FLASK_PORT=5000 FLASK_SECRET_KEY=e2e-flask-secret-0123456789abcdef EMAIL_CONFIRMATION_REQUIRED=false \
    BCRYPT_ROUNDS=4 DATABASE_URL="postgresql://login_service_user:$PW_login@$PGHOST_PORT/$DB"
run soap    soap    SOAP_PORT=5001 SOAP_HOST=127.0.0.1 FLASK_ENV=production \
    DATABASE_URL="postgresql://soap_service_user:$PW_soap@$PGHOST_PORT/$DB"
for s in users:5002 authors:5003 pedidos:5004 pagos:5005; do
  name=${s%%:*}; port=${s##*:}
  pw_var="PW_$name"
  run "$name" "$name" FLASK_PORT=$port BCRYPT_ROUNDS=4 DATABASE_URL="postgresql://${name}_service_user:${!pw_var}@$PGHOST_PORT/$DB"
done
up() { # cualquier respuesta HTTP (incluso 503) significa que el servicio está arriba
  python - "$1" <<'PY'
import sys, urllib.error, urllib.request
try:
    urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=2)
except urllib.error.HTTPError:
    pass
except Exception:
    sys.exit(1)
PY
}
for i in $(seq 1 40); do
  ok=1
  for p in 5000 5001 5002 5003 5004 5005; do up "$p" || ok=0; done
  [ $ok = 1 ] && { echo "los 6 servicios responden"; exit 0; }
  sleep 0.5
done
echo "ALGÚN SERVICIO NO ARRANCÓ"; tail -n 5 /tmp/*.log; exit 1
