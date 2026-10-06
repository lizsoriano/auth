#!/bin/bash
# Capturas con curl PARA BLACKBOARD, ejecutadas EN LA VM contra los 6 servicios reales (por Nginx).
#
#   cd /opt/auth && git pull && bash deploy/evidencias_curl_vm.sh
#
# Hace, en este orden:
#   1. Pide por teclado (sin mostrarla) la contraseña de `library_user`, solo para crear/desactivar usuarios demo.
#   2. Crea demo-admin@ / demo-staff@ / demo-customer@example.com con una contraseña aleatoria (no se imprime ni se guarda).
#   3. Corre e2e/evidencias_curl.sh: 10 capturas (petición + respuesta), cada una en pantalla limpia; pulsa Enter entre capturas.
#      La captura 10 apaga y vuelve a encender Redis con systemctl.
#   4. Al terminar (o si se interrumpe) vuelve a encender Redis y DESACTIVA los 3 usuarios demo.
# El JWT y la contraseña de Redis se leen de los .env sin imprimirse; los tokens salen recortados en pantalla.
set -uo pipefail
REPO=${REPO:-/opt/auth}
HOST=${PGHOST:-localhost}; DB=${DB:-library_db}; LIB_USER=${LIB_USER:-library_user}
VENV=/tmp/e2e-venv
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
[ -f "$REPO/e2e/evidencias_curl.sh" ] || die "no encuentro $REPO/e2e/evidencias_curl.sh (haz git pull)"
[ -f "$REPO/services/login/.env" ] || die "no existe $REPO/services/login/.env (corre primero deploy/setup_microservices_vm.sh)"
command -v curl >/dev/null || die "falta curl"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" && "$VENV/bin/pip" install -q requests bcrypt "psycopg[binary]" redis PyJWT || die "no se pudo preparar $VENV"
fi
read -r -s -p "Contraseña de '$LIB_USER' (solo para crear/desactivar usuarios demo): " LIBRARY_PW; echo
[ -n "$LIBRARY_PW" ] || die "contraseña vacía"
export ADMIN_DSN="postgresql://$LIB_USER:$(python3 -c 'import sys,urllib.parse as u; print(u.quote(sys.argv[1], safe=""))' "$LIBRARY_PW")@$HOST:5432/$DB"
unset LIBRARY_PW
export DEMO_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(14))')
export REDIS_URL=$(grep -m1 '^REDIS_URL=' "$REPO/services/login/.env" | cut -d= -f2-)
export PYREDIS="$VENV/bin/python"

cleanup() {
  sudo systemctl start redis >/dev/null 2>&1
  "$VENV/bin/python" - <<'PYEOF' >/dev/null 2>&1
import os, psycopg
with psycopg.connect(os.environ["ADMIN_DSN"], autocommit=True) as c:
    c.execute("UPDATE users SET is_active = false WHERE email IN ('demo-admin@example.com','demo-staff@example.com','demo-customer@example.com')")
PYEOF
  echo; echo "(Redis encendido y usuarios demo desactivados.)"
}
trap cleanup EXIT

"$VENV/bin/python" "$REPO/e2e/seed_demo_users.py" || die "no se pudieron crear los usuarios demo"
export VM=http://localhost
export REDIS_DOWN_CMD="sudo systemctl stop redis" REDIS_UP_CMD="sudo systemctl start redis"
bash "$REPO/e2e/evidencias_curl.sh"
