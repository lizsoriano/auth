#!/bin/bash
# Despliega EN LA VM el servidor de rastreo (services/gps) detras de Nginx: /gps/ -> 127.0.0.1:5900.
# Idempotente. Se ejecuta en la VM, desde el repo (/opt/auth):   sudo bash deploy/setup_gps_vm.sh
#
# Que hace:
#   1. venv + dependencias de services/gps (Flask, Flask-Sock, gunicorn, PyJWT).
#   2. services/gps/.env (600): el MISMO JWT_SECRET_KEY que login (se copia, nunca se imprime) y PEDIDOS_URL.
#   3. unit systemd gps.service y la ubicacion /gps/ en Nginx (con las cabeceras de WebSocket).
# No abre puertos en el firewall de GCP: el servicio queda en 127.0.0.1 y solo Nginx (80/443) lo publica.
set -euo pipefail
REPO=${REPO:-/opt/auth}
SVC_USER=${SVC_USER:-rutil}
GPS_DIR="$REPO/services/gps"
say() { printf '\n== %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }
envget() { grep -E "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true; }

[ "$(id -u)" = 0 ] || die "ejecuta con sudo"
[ -d "$GPS_DIR" ] || die "no existe $GPS_DIR (actualiza el repo: git pull)"
[ -f "$GPS_DIR/gps_service/tracking.py" ] || die "este checkout no tiene el rastreo de pedidos (services/gps/gps_service/tracking.py)"

say "1) venv y dependencias"
sudo -u "$SVC_USER" python3 -m venv "$GPS_DIR/.venv"
sudo -u "$SVC_USER" "$GPS_DIR/.venv/bin/pip" install -q -r "$GPS_DIR/requirements.txt" gunicorn

say "2) .env (600) con el JWT_SECRET_KEY de login"
JWT=$(envget "$REPO/services/login/.env" JWT_SECRET_KEY)
[ ${#JWT} -ge 32 ] || JWT=$(envget "$REPO/services/login/.env" JWT_SECRET)
[ ${#JWT} -ge 32 ] || die "no encontre JWT_SECRET_KEY (>= 32 caracteres) en $REPO/services/login/.env"
ISSUER=$(envget "$REPO/services/login/.env" JWT_ISSUER)
umask 077
cat > "$GPS_DIR/.env" <<EOF
JWT_SECRET_KEY=$JWT
JWT_ISSUER=${ISSUER:-library-login}
PEDIDOS_URL=http://127.0.0.1:5004
TRACKING_TIME_SCALE=30
GPS_LOG_LEVEL=INFO
EOF
chown "$SVC_USER":"$SVC_USER" "$GPS_DIR/.env"
chmod 600 "$GPS_DIR/.env"

say "3) systemd y Nginx"
install -m 644 "$REPO/deploy/gps.service" /etc/systemd/system/gps.service
install -m 644 "$REPO/deploy/nginx-gps-proxy.conf" /etc/nginx/default.d/library-gps.conf
systemctl daemon-reload
systemctl enable --now gps.service
systemctl restart gps.service
nginx -t
systemctl reload nginx

say "4) Comprobacion"
sleep 2
systemctl is-active gps.service
curl -s http://127.0.0.1:5900/health; echo
curl -s -o /dev/null -w "GET /gps/health por Nginx -> HTTP %{http_code}\n" http://127.0.0.1/gps/health
echo
echo "Listo. En la app Java: Conexion -> Instancia de GCP -> la IP de la VM (el rastreo queda en http://<IP>/gps)."
