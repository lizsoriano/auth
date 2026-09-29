#!/bin/bash
# Despliega TODO lo nuevo de esta ronda en una sola pasada:
#   - Books (soap, 5001): CRUD completo (POST/PUT/PATCH/DELETE /books)
#   - Login (5000): PATCH /profile y POST /session/extend
#
# Aditivo e idempotente. Pide la contraseña de library_user (dueño de las
# tablas) una sola vez; no se muestra ni se guarda.
#
#   bash /opt/auth/deploy/deploy_crud_and_profile.sh
set -euo pipefail

REPO=${REPO:-/opt/auth}
DB=${DB:-library_db}
HOST=${PGHOST:-localhost}
LIB_USER=${LIB_USER:-library_user}
SOAP_DIR=/opt/library_soap_service
LOGIN_DIR="$REPO/services/login"

say(){ printf '\n== %s\n' "$*"; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ -d "$SOAP_DIR" ] || die "no existe $SOAP_DIR"
[ -d "$LOGIN_DIR" ] || die "no existe $LOGIN_DIR"

[ -n "${LIBRARY_PW:-}" ] || read -r -s -p "Contraseña de '$LIB_USER': " LIBRARY_PW
echo
[ -n "$LIBRARY_PW" ] || die "contraseña vacía"

say "1) SQL: CRUD de libros (crea/reemplaza fn_crear_libro, fn_actualizar_libro, fn_eliminar_libro)"
PGPASSWORD="$LIBRARY_PW" psql -h "$HOST" -U "$LIB_USER" -d "$DB" -v ON_ERROR_STOP=1 -q \
  -f "$REPO/services/soap/sql/crud_libros_extension.sql"
echo "ok"

say "2) SQL: permisos para PATCH /profile y POST /session/extend"
PGPASSWORD="$LIBRARY_PW" psql -h "$HOST" -U "$LIB_USER" -d "$DB" -v ON_ERROR_STOP=1 -q \
  -f "$REPO/data/migrations/004_login_profile_and_session_extend_grants.sql"
echo "ok"

say "3) Código: books (rest_api.py, db/repository.py, db/errors.py)"
cp "$REPO/services/soap/rest_api.py" "$SOAP_DIR/rest_api.py"
cp "$REPO/services/soap/db/repository.py" "$SOAP_DIR/db/repository.py"
cp "$REPO/services/soap/db/errors.py" "$SOAP_DIR/db/errors.py"
"$SOAP_DIR/.venv/bin/python" -m py_compile "$SOAP_DIR/rest_api.py" "$SOAP_DIR/db/repository.py" "$SOAP_DIR/db/errors.py"
sudo systemctl restart soap
sleep 2
echo "soap.service: $(systemctl is-active soap)"

say "4) Código: login (repository.py, auth.py, routes.py) -- login.service usa /opt/auth directo, solo se reinicia"
"$LOGIN_DIR/.venv/bin/python" -m py_compile "$LOGIN_DIR/login_service/repository.py" "$LOGIN_DIR/login_service/auth.py" "$LOGIN_DIR/login_service/routes.py"
sudo systemctl restart login
sleep 2
echo "login.service: $(systemctl is-active login)"

say "5) Verificación rápida"
BASE_S=http://127.0.0.1:5001
BASE_L=http://127.0.0.1:5000
ISBN="0000000000$(date +%s | tail -c 4)"
curl -s -o /dev/null -w 'books:  POST   /books           -> HTTP %{http_code}\n' -X POST "$BASE_S/books?format=json" \
  -H 'Content-Type: application/json' \
  -d "{\"isbn\":\"$ISBN\",\"title\":\"Prueba\",\"publicationYear\":2024,\"price\":10,\"stock\":1,\"category\":\"Prueba\",\"format\":\"Digital\",\"authors\":\"Autor\"}"
curl -s -o /dev/null -w 'books:  PATCH  /books/<isbn>    -> HTTP %{http_code}\n' -X PATCH "$BASE_S/books/$ISBN?format=json" \
  -H 'Content-Type: application/json' -d '{"price":20}'
curl -s -o /dev/null -w 'books:  DELETE /books/<isbn>    -> HTTP %{http_code}\n' -X DELETE "$BASE_S/books/$ISBN?format=json"
curl -s -o /dev/null -w 'login:  GET    /health          -> HTTP %{http_code}\n' "$BASE_L/health?format=json"
say "LISTO."
