#!/bin/bash
# Evidencias para el reporte (cada parte imprime el comando y su resultado, listo para captura de pantalla).
#
#   bash /opt/auth/deploy/evidencias_vm.sh 1                       servicio, puerto 5000 y formatos XML/JSON
#   bash /opt/auth/deploy/evidencias_vm.sh 2 correo+ev1@gmail.com  registro (XML) y validaciones (400/409/403)
#   bash /opt/auth/deploy/evidencias_vm.sh 3 correo+ev1@gmail.com  (tras confirmar el correo) login/session/logout en XML
#   bash /opt/auth/deploy/evidencias_vm.sh 4                       base de datos (pide la contraseña de library_user)
#   bash /opt/auth/deploy/evidencias_vm.sh 5                       pruebas automaticas (pytest)
BASE=${BASE:-http://127.0.0.1:5000}
PART=${1:?uso: evidencias_vm.sh 1|2|3|4|5 [correo]}
EMAIL=${2:-}
PP="python3 -m json.tool --no-ensure-ascii"
PW=${PASSWORD:-ClaveSegura123}
H='-H "Content-Type: application/json"'
JAR=/tmp/evidencias_cookies.txt
show(){ printf '\n$ %s\n' "$1"; bash -c "$1"; echo; }
need_email(){ [ -n "$EMAIL" ] || { echo "falta el correo: bash evidencias_vm.sh $PART correo+ev1@gmail.com"; exit 1; }; }

case "$PART" in
1)
  show "systemctl status login --no-pager | head -6"
  show "ss -ltnp | grep 5000"
  show "curl -s $BASE/health"
  show "curl -s \"$BASE/health?format=xml\""
  show "curl -s \"$BASE/health?format=json\" | $PP"
  show "curl -s -o /dev/null -w 'sin format  -> HTTP %{http_code}  %{content_type}\n' $BASE/health"
  show "curl -s -o /dev/null -w 'format=json -> HTTP %{http_code}  %{content_type}\n' \"$BASE/health?format=json\""
  ;;
2)
  need_email
  REG="{\"nombre\":\"Ruth\",\"apellido_paterno\":\"Soriano\",\"apellido_materno\":\"Evidencia\",\"email\":\"$EMAIL\",\"password\":\"$PW\"}"
  show "curl -s -X POST \"$BASE/register\" $H -d '$REG'"
  echo ">> Llega el correo 'Confirma tu cuenta de Library' (captura del correo y del clic que abre el JSON)"
  show "curl -s -X POST \"$BASE/login\" $H -d '{\"email\":\"$EMAIL\",\"password\":\"$PW\"}'"
  show "curl -s -X POST \"$BASE/register?format=json\" $H -d '$REG' | $PP"
  show "curl -s -X POST \"$BASE/register?format=json\" $H -d '{\"nombre\":\"Ana\",\"apellido_paterno\":\"L\",\"apellido_materno\":\"D\",\"email\":\"correo-invalido\",\"password\":\"123\"}' | $PP"
  show "curl -s -X POST \"$BASE/register\" $H -d '{\"nombre\":\"Ana\"}'"
  ;;
3)
  need_email
  show "curl -s -X POST \"$BASE/login\" $H -d '{\"email\":\"$EMAIL\",\"password\":\"$PW\"}' -c $JAR"
  show "curl -s \"$BASE/session\" -b $JAR"
  show "curl -s -X POST \"$BASE/logout\" -b $JAR -c $JAR"
  show "curl -s \"$BASE/session\" -b $JAR"
  show "curl -s -X POST \"$BASE/login?format=json\" $H -d '{\"email\":\"$EMAIL\",\"password\":\"incorrecta\"}' | $PP"
  ;;
4)
  read -r -s -p "Contraseña de library_user: " PGPASSWORD; echo; export PGPASSWORD
  P="psql -h localhost -U library_user -d library_db"
  show "$P -c '\\dt'"
  show "$P -c '\\d users'"
  show "$P -c \"select user_id, email, left(password_hash,7) as prefijo_bcrypt, length(password_hash) as largo, email_verified_at is not null as verificado from users where email like 'rutilia2511%' order by user_id\""
  show "$P -c '\\d login_sessions'"
  show "$P -c '\\d email_verifications'"
  ;;
5)
  D=/opt/auth/apps/services/login; [ -d "$D" ] || D=/opt/auth/services/login
  show "cd $D && .venv/bin/pip install -q pytest 2>&1 | tail -1; .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -5"
  ;;
*) echo "parte invalida"; exit 1;;
esac
