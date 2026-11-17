#!/bin/bash
# Despliega EN LA VM el API Gateway (services/gateway) y deja a Nginx como unica puerta publica hacia el.
# Idempotente. Se ejecuta en la VM, desde el repo (/opt/auth):
#   sudo bash deploy/setup_gateway_vm.sh              instalar
#   sudo bash deploy/setup_gateway_vm.sh --rollback   volver a los .conf por servicio de Nginx
#
# Que hace:
#   1. venv + dependencias de services/gateway (Flask, Flask-Sock, requests, websocket-client, gunicorn).
#   2. services/gateway/.env (sin secretos) a partir de .env.example si no existe.
#   3. unit systemd gateway.service (127.0.0.1:8080).
#   4. Nginx: instala library-gateway.conf y APARTA los .conf por servicio (soap-proxy, auth-proxy, library-microservices,
#      library-gps) a /etc/nginx/default.d.gateway-backup/ para que la unica ruta sea Nginx -> gateway -> servicios.
#      /library (monolito de portadas) NO se toca. Si `nginx -t` falla, se restaura todo solo.
#   5. Comprueba /gateway/health.
# No abre puertos en el firewall de GCP: el gateway y los servicios quedan en 127.0.0.1; sigue siendo Nginx (80/443) el unico publico.
# No hace falta dominio: Nginx atiende por IP, como hasta ahora.
set -euo pipefail
REPO=${REPO:-/opt/auth}
SVC_USER=${SVC_USER:-rutil}
GW_DIR="$REPO/services/gateway"
NGX_DIR=/etc/nginx/default.d
BACKUP_DIR=/etc/nginx/default.d.gateway-backup
OLD_CONFS=(soap-proxy.conf auth-proxy.conf library-microservices.conf library-gps.conf)
say() { printf '\n== %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "ejecuta con sudo"

restore_old() {
  [ -d "$BACKUP_DIR" ] || return 0
  for f in "${OLD_CONFS[@]}"; do [ -f "$BACKUP_DIR/$f" ] && cp -f "$BACKUP_DIR/$f" "$NGX_DIR/$f"; done
  rm -f "$NGX_DIR/library-gateway.conf"
}

if [ "${1:-}" = "--rollback" ]; then
  say "Rollback: Nginx vuelve a los .conf por servicio"
  [ -d "$BACKUP_DIR" ] || die "no existe $BACKUP_DIR (no hay nada que restaurar)"
  restore_old
  nginx -t && systemctl reload nginx
  echo "Listo. El gateway sigue instalado pero Nginx ya no le envia trafico (systemctl stop gateway para apagarlo)."
  exit 0
fi

[ -d "$GW_DIR" ] || die "no existe $GW_DIR (actualiza el repo: git pull)"
[ -f "$GW_DIR/gateway_service/app.py" ] || die "este checkout no tiene el gateway (services/gateway)"

say "1) venv y dependencias"
sudo -u "$SVC_USER" python3 -m venv "$GW_DIR/.venv"
sudo -u "$SVC_USER" "$GW_DIR/.venv/bin/pip" install -q -r "$GW_DIR/requirements.txt" gunicorn

say "2) .env (sin secretos)"
# systemd no admite comentarios en la misma linea que el valor (VAR=3  # texto): si el .env los trae, se rehace desde el ejemplo.
if [ -f "$GW_DIR/.env" ] && grep -Eq '^[A-Z_]+=[^#]*[[:space:]]#' "$GW_DIR/.env"; then
  mv -f "$GW_DIR/.env" "$GW_DIR/.env.bak"
fi
if [ ! -f "$GW_DIR/.env" ]; then
  install -m 644 -o "$SVC_USER" -g "$SVC_USER" "$GW_DIR/.env.example" "$GW_DIR/.env"
fi

# Los puertos de la VM pueden no ser los del repo (p. ej. users 5004, authors 5005, pedidos 5003, pagos 5002): se leen del
# `-b/--bind` de la unit systemd de cada servicio y se escriben en el .env del gateway, para que /users llegue a users, etc.
set_env() { # set_env CLAVE VALOR
  if grep -q "^$1=" "$GW_DIR/.env"; then sed -i "s#^$1=.*#$1=$2#" "$GW_DIR/.env"; else echo "$1=$2" >> "$GW_DIR/.env"; fi
}
for svc in login:AUTH soap:SOAP users:USERS authors:AUTHORS pedidos:PEDIDOS pagos:PAGOS gps:GPS; do
  unit=${svc%%:*}; var=${svc##*:}
  port=$(systemctl cat "$unit.service" 2>/dev/null | grep -E '^ExecStart=' | grep -oE '(-b|--bind)[ =]+[0-9a-zA-Z.]+:[0-9]+' | head -1 | grep -oE '[0-9]+$' || true)
  if [ -n "$port" ]; then set_env "${var}_URL" "http://127.0.0.1:$port"; echo "  $unit -> 127.0.0.1:$port"; else echo "  $unit: sin unit (se usa el puerto por defecto)"; fi
done

say "3) servicio systemd gateway"
install -m 644 "$REPO/deploy/gateway.service" /etc/systemd/system/gateway.service
systemctl daemon-reload
systemctl enable --now gateway
systemctl restart gateway
for i in $(seq 1 20); do
  curl -fs -m 2 http://127.0.0.1:8080/health >/dev/null 2>&1 && break
  sleep 1
  [ "$i" = 20 ] && { journalctl -u gateway -n 20 --no-pager; die "el gateway no responde en 127.0.0.1:8080"; }
done
echo "gateway arriba: $(curl -s http://127.0.0.1:8080/health)"

say "4) Nginx: unica puerta -> gateway"
mkdir -p "$BACKUP_DIR"
for f in "${OLD_CONFS[@]}"; do
  if [ -f "$NGX_DIR/$f" ]; then cp -n "$NGX_DIR/$f" "$BACKUP_DIR/$f"; rm -f "$NGX_DIR/$f"; echo "  apartado: $f"; fi
done
install -m 644 "$REPO/deploy/nginx-gateway-proxy.conf" "$NGX_DIR/library-gateway.conf"
if ! NGX=$(nginx -t 2>&1); then
  echo "$NGX"; restore_old; nginx -t >/dev/null 2>&1 || true
  die "nginx -t fallo: se restauraron los .conf anteriores (no se recargo Nginx)"
fi
systemctl reload nginx

say "5) comprobacion"
sleep 1
curl -fs -m 5 http://127.0.0.1/gateway/health && echo
echo
echo "Listo: apps -> Nginx:80 -> gateway:8080 -> servicios en 127.0.0.1. Para volver atras:  sudo bash deploy/setup_gateway_vm.sh --rollback"
