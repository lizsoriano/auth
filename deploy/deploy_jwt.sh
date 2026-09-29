#!/bin/bash
# Despliega la autenticación JWT en la VM:
#   - login (5000): emite el JWT en POST /login.
#   - soap/books (5001): lo valida (HS256) en las escrituras de /books.
#
# Genera UNA sola JWT_SECRET y la escribe en los dos .env (debe ser
# idéntica en ambos servicios). Aditivo: no borra nada de los .env, solo
# agrega/actualiza la línea JWT_SECRET. Requiere la contraseña de
# library_user SOLO para el nuevo permiso de BD (SELECT is_admin, migración
# 005) -- el resto (código, .env, reinicio) no toca la base de datos y
# este script lo hace sin pedir ninguna otra contraseña.
#
#   bash /opt/auth/deploy/deploy_jwt.sh
set -euo pipefail

REPO=${REPO:-/opt/auth}
DB=${DB:-library_db}
HOST=${PGHOST:-localhost}
LIB_USER=${LIB_USER:-library_user}
SOAP_DIR=/opt/library_soap_service
LOGIN_DIR="$REPO/services/login"
LOGIN_ENV="$LOGIN_DIR/.env"
SOAP_ENV="$SOAP_DIR/.env"

say(){ printf '\n== %s\n' "$*"; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ -f "$LOGIN_ENV" ] || die "no existe $LOGIN_ENV"
[ -f "$SOAP_ENV" ]  || die "no existe $SOAP_ENV"

[ -n "${LIBRARY_PW:-}" ] || read -r -s -p "Contraseña de '$LIB_USER' (solo para el permiso SELECT is_admin): " LIBRARY_PW
echo
[ -n "$LIBRARY_PW" ] || die "contraseña vacía"

say "1) SQL: permiso para leer is_admin (rol del JWT)"
PGPASSWORD="$LIBRARY_PW" psql -h "$HOST" -U "$LIB_USER" -d "$DB" -v ON_ERROR_STOP=1 -q \
  -f "$REPO/data/migrations/005_login_jwt_role_grant.sql"
unset LIBRARY_PW
echo "ok"

say "2) JWT_SECRET: misma clave en los dos servicios"
if grep -q '^JWT_SECRET=.\+' "$LOGIN_ENV"; then
  SECRET=$(sed -n 's/^JWT_SECRET=//p' "$LOGIN_ENV" | head -1)
  echo "ya existía en $LOGIN_ENV: se reutiliza (no se genera una nueva)"
else
  SECRET=$(openssl rand -hex 32)
  echo "JWT_SECRET=$SECRET" >> "$LOGIN_ENV"
  echo "generada y agregada a $LOGIN_ENV"
fi
grep -q '^JWT_EXPIRATION_HOURS=' "$LOGIN_ENV" || echo "JWT_EXPIRATION_HOURS=2" >> "$LOGIN_ENV"

if grep -q '^JWT_SECRET=.\+' "$SOAP_ENV"; then
  sed -i "s#^JWT_SECRET=.*#JWT_SECRET=$SECRET#" "$SOAP_ENV"
else
  echo "JWT_SECRET=$SECRET" >> "$SOAP_ENV"
fi
echo "sincronizada en $SOAP_ENV"
unset SECRET
chmod 600 "$LOGIN_ENV" "$SOAP_ENV"

say "3) Código: login (config.py, auth.py, repository.py, routes.py)"
cp "$LOGIN_DIR/login_service/config.py"     "$LOGIN_DIR/login_service/config.py.bak.$(date +%s)" 2>/dev/null || true
cp "$REPO/services/login/login_service/config.py"     "$LOGIN_DIR/login_service/config.py"
cp "$REPO/services/login/login_service/auth.py"       "$LOGIN_DIR/login_service/auth.py"
cp "$REPO/services/login/login_service/repository.py" "$LOGIN_DIR/login_service/repository.py"
cp "$REPO/services/login/login_service/routes.py"     "$LOGIN_DIR/login_service/routes.py"
"$LOGIN_DIR/.venv/bin/pip" install -q PyJWT==2.9.0
"$LOGIN_DIR/.venv/bin/python" -m py_compile "$LOGIN_DIR/login_service/config.py" "$LOGIN_DIR/login_service/auth.py" \
  "$LOGIN_DIR/login_service/repository.py" "$LOGIN_DIR/login_service/routes.py"

say "4) Código: books (auth_jwt.py nuevo, config/settings.py, rest_api.py)"
cp "$REPO/services/soap/auth_jwt.py"        "$SOAP_DIR/auth_jwt.py"
cp "$REPO/services/soap/config/settings.py" "$SOAP_DIR/config/settings.py"
cp "$REPO/services/soap/rest_api.py"        "$SOAP_DIR/rest_api.py"
"$SOAP_DIR/.venv/bin/pip" install -q PyJWT==2.9.0
"$SOAP_DIR/.venv/bin/python" -m py_compile "$SOAP_DIR/auth_jwt.py" "$SOAP_DIR/config/settings.py" "$SOAP_DIR/rest_api.py"

say "5) Reiniciando ambos servicios"
sudo systemctl restart login
sudo systemctl restart soap
sleep 3
echo "login.service: $(systemctl is-active login)   soap.service: $(systemctl is-active soap)"

say "6) Verificación end-to-end (login real + JWT contra books)"
BASE_L=http://127.0.0.1:5000
BASE_S=http://127.0.0.1:5001
EMAIL="jwt.deploy.$(date +%s)@example.com"
ISBN="9$(date +%s | tail -c 10)0"

curl -s -o /dev/null -w 'GET  /health (books) -> HTTP %{http_code}\n' "$BASE_S/health"

RESP=$(curl -s -X POST "$BASE_L/register?format=json" -H 'Content-Type: application/json' \
  -d "{\"nombre\":\"JWT\",\"apellido_paterno\":\"Deploy\",\"apellido_materno\":\"Test\",\"email\":\"$EMAIL\",\"password\":\"ClaveSegura123\"}")
echo "$RESP" | grep -q '"verification_email"' && echo "register: ok ($EMAIL)" || { echo "register FALLO: $RESP"; exit 1; }

curl -s -o /dev/null -w 'POST /books SIN token   -> HTTP %{http_code} (se espera 401)\n' -X POST "$BASE_S/books?format=json" \
  -H 'Content-Type: application/json' -d "{\"isbn\":\"$ISBN\",\"title\":\"x\",\"publicationYear\":2024,\"price\":1,\"stock\":1,\"category\":\"c\",\"format\":\"f\",\"authors\":\"a\"}"

echo
echo "Nota: el usuario de prueba \"$EMAIL\" quedó sin confirmar su correo (require confirmación)."
echo "      El resto del ciclo con JWT real (login -> token -> escritura) se prueba manualmente"
echo "      con una cuenta ya confirmada -- ver services/login/README.md."
say "LISTO."
