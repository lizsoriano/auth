#!/bin/bash
# Crea (o reactiva) 3 usuarios de prueba EN LA VM para usar la app Python Tk, Postman o curl con los 6 microservicios:
#   demo-admin@example.com (rol admin) · demo-staff@example.com (rol staff) · demo-customer@example.com (rol customer)
# La contraseña la eliges tú (se pide en silencio dos veces); no se imprime ni se guarda en ningún archivo.
#
#   cd /opt/auth && git pull && bash deploy/crear_usuarios_demo_vm.sh              # crear / reactivar
#   bash deploy/crear_usuarios_demo_vm.sh --desactivar                             # al terminar la entrega
# Pide también la contraseña de `library_user`, solo para escribir en la base (igual que los otros scripts de deploy/).
set -uo pipefail
REPO=${REPO:-/opt/auth}
HOST=${PGHOST:-localhost}; DB=${DB:-library_db}; LIB_USER=${LIB_USER:-library_user}
VENV=/tmp/e2e-venv
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
[ -f "$REPO/e2e/seed_demo_users.py" ] || die "no encuentro $REPO/e2e/seed_demo_users.py (haz git pull)"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" && "$VENV/bin/pip" install -q requests bcrypt "psycopg[binary]" redis PyJWT || die "no se pudo preparar $VENV"
fi

read -r -s -p "Contraseña de '$LIB_USER' (solo para escribir en la base): " LIBRARY_PW; echo
[ -n "$LIBRARY_PW" ] || die "contraseña vacía"
export ADMIN_DSN="postgresql://$LIB_USER:$(python3 -c 'import sys,urllib.parse as u; print(u.quote(sys.argv[1], safe=""))' "$LIBRARY_PW")@$HOST:5432/$DB"
unset LIBRARY_PW

if [ "${1:-}" = "--desactivar" ]; then
  "$VENV/bin/python" - <<'PYEOF' || die "no se pudieron desactivar"
import os, psycopg
with psycopg.connect(os.environ["ADMIN_DSN"], autocommit=True) as c:
    n = c.execute("UPDATE users SET is_active = false WHERE email IN ('demo-admin@example.com','demo-staff@example.com','demo-customer@example.com')").rowcount
print(f"usuarios demo desactivados: {n}")
PYEOF
  exit 0
fi

read -r -s -p "Contraseña para los usuarios demo (mínimo 10 caracteres): " P1; echo
read -r -s -p "Repítela: " P2; echo
[ "$P1" = "$P2" ] || die "las contraseñas no coinciden"
[ ${#P1} -ge 10 ] || die "usa al menos 10 caracteres"
[ ${#P1} -le 72 ] || die "máximo 72 caracteres (límite de bcrypt)"
export DEMO_PASSWORD="$P1"; unset P1 P2
"$VENV/bin/python" "$REPO/e2e/seed_demo_users.py" || die "no se pudieron crear los usuarios"
echo "Listo. Entra a la app con demo-admin@example.com / demo-staff@example.com / demo-customer@example.com y la contraseña que acabas de elegir."
