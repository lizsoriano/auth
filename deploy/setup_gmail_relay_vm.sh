#!/bin/bash
# Configura Postfix (postfix.service) para entregar correo a Gmail por el puerto 587 (Google Cloud bloquea el 25).
#
#   bash /opt/auth/deploy/setup_gmail_relay_vm.sh
#
# Pide POR TECLADO tu cuenta de Gmail y una CONTRASEÑA DE APLICACION de Google (myaccount.google.com/apppasswords;
# requiere verificación en 2 pasos). La contraseña solo se escribe en /etc/postfix/sasl_passwd (root, permisos 600).
# CentOS Stream 10 ya no soporta 'hash:' (Berkeley DB): se usa 'lmdb:'.
set -uo pipefail

REPO=${REPO:-/opt/auth}
ENVFILE=$REPO/services/login/.env
SASL=${SASL:-/etc/postfix/sasl_passwd}
RELAY=${RELAY:-[smtp.gmail.com]:587}
TLS_LEVEL=${TLS_LEVEL:-encrypt}
SUDO=${SUDO-sudo}
RESTART_POSTFIX=${RESTART_POSTFIX:-$SUDO systemctl restart postfix}

say(){ printf '\n== %s\n' "$*"; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v postconf >/dev/null || die "postfix no esta instalado (sudo dnf install -y postfix postfix-lmdb)"
postconf -m | grep -qx lmdb || die "postfix no tiene soporte lmdb (sudo dnf install -y postfix-lmdb)"

say "Datos (la contraseña no se muestra)"
[ -n "${GMAIL:-}" ]  || read -r -p "  Tu cuenta de Gmail (la que enviara los correos): " GMAIL
[ -n "${APP_PW:-}" ] || { read -r -s -p "  Contraseña de aplicacion de Google (16 letras): " APP_PW; echo; }
GMAIL=${GMAIL// /}; APP_PW=${APP_PW// /}          # Google la muestra con espacios
[[ "$GMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "el correo '$GMAIL' no parece valido"
[[ "$APP_PW" =~ ^[A-Za-z0-9]{16}$ ]] || die "la contraseña de aplicacion debe tener 16 letras/numeros (sin espacios). No es tu contraseña normal de Gmail."

say "1) Credenciales del relay ($SASL, solo root)"
( umask 077; printf '%s %s:%s\n' "$RELAY" "$GMAIL" "$APP_PW" | $SUDO tee "$SASL" >/dev/null )
$SUDO chmod 600 "$SASL"; $SUDO postmap "lmdb:$SASL" || die "postmap fallo"
$SUDO chmod 600 "$SASL".lmdb 2>/dev/null; unset APP_PW
echo "sasl_passwd y sasl_passwd.lmdb listos (permisos 600)"

say "2) Configuracion de Postfix"
$SUDO postconf -e "relayhost = $RELAY" \
  'smtp_sasl_auth_enable = yes' "smtp_sasl_password_maps = lmdb:$SASL" \
  'smtp_sasl_security_options = noanonymous' 'smtp_sasl_tls_security_options = noanonymous' \
  "smtp_tls_security_level = $TLS_LEVEL" 'smtp_tls_CAfile = /etc/pki/tls/certs/ca-bundle.crt' \
  'inet_interfaces = loopback-only' 'inet_protocols = ipv4'
$SUDO postfix check && echo "postfix check: ok"
$RESTART_POSTFIX && echo "postfix reiniciado"
sleep 2

if [ -f "$ENVFILE" ]; then
  say "3) Remitente del servicio login (Gmail reescribe el remitente a la cuenta autenticada)"
  sed -i "s#^MAIL_FROM=.*#MAIL_FROM=\"Library <$GMAIL>\"#" "$ENVFILE"
  grep '^MAIL_FROM=' "$ENVFILE"
  if [ "${SKIP_SERVICE:-0}" != 1 ] && systemctl is-active --quiet login 2>/dev/null; then sudo systemctl restart login && echo "login.service reiniciado"; fi
fi

say "4) Correo de prueba a $GMAIL"
printf 'From: Library <%s>\nTo: %s\nSubject: Prueba de Postfix (maquina-02)\nContent-Type: text/plain; charset=utf-8\n\nSi lees esto, Postfix ya entrega a Gmail por el puerto 587.\n' "$GMAIL" "$GMAIL" \
  | /usr/sbin/sendmail -t -f "$GMAIL" || die "sendmail fallo"
$SUDO postqueue -f
for i in $(seq 1 15); do sleep 2; $SUDO postqueue -p | grep -q "$GMAIL" || break; done
echo "--- resultado de la entrega:"
LOG=$($SUDO journalctl -t postfix/smtp --no-pager -n 40 2>/dev/null; $SUDO tail -n 40 /var/log/maillog 2>/dev/null)
echo "$LOG" | grep -E "status=(sent|deferred|bounced)" | tail -2 | cut -c1-230
if echo "$LOG" | grep -q "status=sent" && ! $SUDO postqueue -p | grep -q "$GMAIL"; then
  echo; echo "OK: el correo salio por $RELAY. Revisa la bandeja de $GMAIL (y spam)."
else
  echo; echo "AUN NO SALIO. Causas comunes:"
  echo "  - 'Username and Password not accepted' -> contraseña de aplicacion incorrecta o cuenta sin verificacion en 2 pasos"
  echo "  - 'Connection timed out' al puerto 25   -> revisa que relayhost sea $RELAY (Google Cloud bloquea el 25)"
  echo "  - cola: sudo postqueue -p   |   log: sudo journalctl -u postfix -n 50 --no-pager"
fi
