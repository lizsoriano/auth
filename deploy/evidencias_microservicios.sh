#!/bin/bash
# Evidencia de punta a punta EN LA VM: los 6 servicios reales + PostgreSQL + Redis, incluida la caída de Redis.
#
#   bash /opt/auth/deploy/evidencias_microservicios.sh
#
# Corre e2e/e2e_scenario.py (el mismo escenario que se probó en Docker) en 3 fases:
#   A  flujo normal: login, JWT de 20 min, books/authors/users/pedidos/pagos, caché, refresh, logout y revocación.
#   B  `sudo systemctl stop redis`  -> lecturas cacheadas siguen; sesión/revocación/autorización/pagos dan 503.
#   C  `sudo systemctl start redis` -> lo revocado sigue revocado (AOF) y todo vuelve; se borra lo creado.
# Crea usuarios y datos de prueba (e2e-*@example.com, «Libro E2E») y los BORRA al final. Pide la contraseña de
# `library_user` por teclado (solo para preparar/limpiar esos datos); el JWT y la REDIS_URL se leen de los .env
# sin imprimirse. Si algo se interrumpe a medias, Redis se vuelve a arrancar al salir.
set -uo pipefail
REPO=${REPO:-/opt/auth}
HOST=${PGHOST:-localhost}; DB=${DB:-library_db}; LIB_USER=${LIB_USER:-library_user}
LOGIN_ENV=$REPO/services/login/.env
VENV=/tmp/e2e-venv

envget(){ grep -m1 "^$2=" "$1" | cut -d= -f2-; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
[ -f "$LOGIN_ENV" ] || die "no existe $LOGIN_ENV (corre primero deploy/setup_microservices_vm.sh)"
[ -f "$REPO/e2e/e2e_scenario.py" ] || die "no encuentro $REPO/e2e/e2e_scenario.py (git pull)"
trap 'sudo systemctl start redis >/dev/null 2>&1' EXIT   # pase lo que pase, Redis queda arriba

export JWT_SECRET_KEY=$(envget "$LOGIN_ENV" JWT_SECRET_KEY)
export REDIS_URL=$(envget "$LOGIN_ENV" REDIS_URL)
[ ${#JWT_SECRET_KEY} -ge 32 ] && [ -n "$REDIS_URL" ] || die "faltan JWT_SECRET_KEY/REDIS_URL en $LOGIN_ENV"
read -r -s -p "Contraseña de '$LIB_USER' (solo para crear/borrar datos de prueba): " LIBRARY_PW; echo
[ -n "$LIBRARY_PW" ] || die "contraseña vacía"
export ADMIN_DSN="postgresql://$LIB_USER:$(python3 -c 'import sys,urllib.parse as u; print(u.quote(sys.argv[1], safe=""))' "$LIBRARY_PW")@$HOST:5432/$DB"
unset LIBRARY_PW

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" && "$VENV/bin/pip" install -q requests bcrypt "psycopg[binary]" redis PyJWT || die "no se pudo preparar $VENV"
fi
phase(){ "$VENV/bin/python" "$REPO/e2e/e2e_scenario.py" "$1"; }

rc=0
echo; echo "################ FASE A: flujo normal ################";                phase A || rc=1
echo; echo "################ FASE B: REDIS CAÍDO (systemctl stop redis) ################"
sudo systemctl stop redis || die "no se pudo detener redis"; phase B || rc=1
echo; echo "################ FASE C: Redis de vuelta (systemctl start redis) ################"
sudo systemctl start redis || die "no se pudo arrancar redis"; sleep 2; phase C || rc=1

echo; echo "== ¿se coló algún token o contraseña en los logs de los servicios? (journalctl, última hora)"
if sudo journalctl -u login -u soap -u users -u authors -u pedidos -u pagos --since "-1h" --no-pager 2>/dev/null \
   | grep -E "eyJ[A-Za-z0-9_-]{10,}|$JWT_SECRET_KEY" >/dev/null; then echo "  ✘ SÍ: hay un JWT o el secreto en los logs"; rc=1
else echo "  ✔ no: ni JWT ni JWT_SECRET_KEY aparecen en los logs"; fi
[ $rc = 0 ] && echo "EVIDENCIA COMPLETA: OK" || echo "HAY FALLAS: revisa las líneas ✘"
exit $rc
