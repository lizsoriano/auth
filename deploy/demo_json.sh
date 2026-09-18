#!/bin/bash
# Demostracion con comandos: cada peticion se ve con su respuesta en JSON formateado.
#
#   Paso 1 (salud + registro; llega el correo):   bash /opt/auth/deploy/demo_json.sh tu_correo@gmail.com
#   Paso 2 (confirmar + login + sesion + logout): bash /opt/auth/deploy/demo_json.sh tu_correo@gmail.com TOKEN
#
# TOKEN es lo que va despues de /verify/ en el enlace del correo (tambien viene escrito en el correo).
# Alternativa al paso 2: hacer clic en "Da clic aqui para confirmar tu cuenta" en el correo (abre el JSON).
BASE=${BASE:-http://127.0.0.1:5000}
EMAIL=${1:?uso: demo_json.sh correo@gmail.com [TOKEN]}
TOKEN=${2:-}
NOMBRE=${NOMBRE:-Ruth}; PATERNO=${PATERNO:-Soriano}; MATERNO=${MATERNO:-Prueba}; PASSWORD=${PASSWORD:-ClaveSegura123}
JAR=$(mktemp)
PP="python3 -m json.tool --no-ensure-ascii"

show(){ printf '\n$ %s\n' "$1"; bash -c "$1"; }

BODY_REG="{\"nombre\":\"$NOMBRE\",\"apellido_paterno\":\"$PATERNO\",\"apellido_materno\":\"$MATERNO\",\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
BODY_LOGIN="{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
H='-H "Content-Type: application/json"'

if [ -z "$TOKEN" ]; then
  show "ss -ltnp | grep 5000"
  show "curl -s \"$BASE/health?format=json\" | $PP"
  show "curl -s -X POST \"$BASE/register?format=json\" $H -d '$BODY_REG' | $PP"
  printf '\n>> Revisa la bandeja de %s: llega "Confirma tu cuenta de Library".\n' "$EMAIL"
  printf '>> Haz clic en "Da clic aqui para confirmar tu cuenta" (abre el JSON) o corre el paso 2 con el token del correo.\n'
else
  show "curl -s \"$BASE/verify/$TOKEN?format=json\" | $PP"
  show "curl -s -X POST \"$BASE/login?format=json\" $H -d '$BODY_LOGIN' -c $JAR | $PP"
  show "curl -s \"$BASE/session?format=json\" -b $JAR | $PP"
  show "curl -s -X POST \"$BASE/logout?format=json\" -b $JAR -c $JAR | $PP"
  show "curl -s \"$BASE/session?format=json\" -b $JAR | $PP"
fi
rm -f "$JAR"
