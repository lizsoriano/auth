#!/bin/bash
# Instala en la VM lo que hoy solo existía como configuración manual:
#   - soap.service   (Flask del servicio SOAP/books, puerto 5001, loopback)
#   - login.service  (gunicorn del servicio login, puerto 5000, loopback -
#                      normalmente ya está si seguiste services/login/README.md;
#                      este script lo deja igual si ya existe)
#   - nginx: location /soap -> 127.0.0.1:5001 (mismo patrón que /library)
#
# Requiere que /opt/library_soap_service y /opt/auth/services/login ya
# existan con su propio .venv y .env (no los crea ni los toca). Idempotente:
# se puede correr varias veces sin efecto adicional. No pide contraseñas de
# PostgreSQL (no toca la base de datos).
#
#   sudo bash deploy/setup_soap_and_nginx_vm.sh
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOAP_DIR=/opt/library_soap_service
LOGIN_DIR=/opt/auth/services/login

say(){ printf '\n== %s\n' "$*"; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ -d "$SOAP_DIR" ]  || die "no existe $SOAP_DIR (con su .venv y .env) — despliega el servicio soap ahí primero"
[ -d "$LOGIN_DIR" ] || die "no existe $LOGIN_DIR — sigue services/login/README.md primero"

say "1) Unidad systemd: soap.service"
sudo cp "$DEPLOY_DIR/soap.service" /etc/systemd/system/soap.service
say "2) Unidad systemd: login.service"
sudo cp "$DEPLOY_DIR/login.service" /etc/systemd/system/login.service

sudo systemctl daemon-reload
sudo systemctl enable --now soap
sudo systemctl enable --now login
sleep 3
echo "soap.service:  $(systemctl is-active soap)   (puerto 5001, loopback)"
echo "login.service: $(systemctl is-active login)  (puerto 5000, loopback)"

say "3) Nginx: location /soap (mismo patrón que /library)"
sudo cp "$DEPLOY_DIR/nginx-soap-proxy.conf" /etc/nginx/default.d/soap-proxy.conf
sudo nginx -t
sudo systemctl reload nginx

say "4) Verificación"
curl -s -o /dev/null -w '/soap/wsdl (local)        -> HTTP %{http_code}\n' http://127.0.0.1:5001/wsdl
curl -s -o /dev/null -w '/soap/books (via nginx)    -> HTTP %{http_code}\n' http://127.0.0.1/soap/books
curl -s -o /dev/null -w '/health del login (local)  -> HTTP %{http_code}\n' http://127.0.0.1:5000/health
curl -s -o /dev/null -w '/library (el monolito, no debe romperse) -> HTTP %{http_code}\n' http://127.0.0.1/library/
say "LISTO."
