#!/bin/bash
# TLS autofirmado para nginx en CentOS. Ejecutar en la VM, después del despliegue.
# Uso: bash deploy/setup_tls_vm.sh IP_O_NOMBRE
set -euo pipefail
TLS_NAME=${1:?Uso: bash deploy/setup_tls_vm.sh IP_O_NOMBRE}
[[ "$TLS_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || { echo 'Nombre/IP inválido' >&2; exit 1; }
for cmd in openssl nginx sudo python3; do command -v "$cmd" >/dev/null; done
sudo -n true
TLS_DIR=/etc/nginx/tls/library
TLS_CONF=/etc/nginx/conf.d/library-tls.conf
sudo install -d -m 700 "$TLS_DIR"
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
san="DNS:$TLS_NAME"
check_name=-verify_hostname
if [[ "$TLS_NAME" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  san="IP:$TLS_NAME"
  check_name=-verify_ip
fi
if sudo test -f "$TLS_DIR/server.crt" && sudo test -f "$TLS_DIR/server.key"; then
  sudo openssl x509 -in "$TLS_DIR/server.crt" -checkend 0 -noout
  sudo openssl verify -CAfile "$TLS_DIR/server.crt" "$check_name" "$TLS_NAME" "$TLS_DIR/server.crt" > /dev/null
else
  umask 077
  openssl req -x509 -nodes -newkey rsa:3072 -days 365 -sha256 \
    -keyout "$tmp/server.key" -out "$tmp/server.crt" \
    -subj "/CN=$TLS_NAME" -addext "subjectAltName=$san"
  sudo install -m 600 "$tmp/server.key" "$TLS_DIR/server.key"
  sudo install -m 644 "$tmp/server.crt" "$TLS_DIR/server.crt"
fi
cat > "$tmp/tls.conf" <<EOF
server {
    listen 443 ssl;
    server_name $TLS_NAME;
    ssl_certificate $TLS_DIR/server.crt;
    ssl_certificate_key $TLS_DIR/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    include /etc/nginx/default.d/*.conf;
}
EOF
# Restaurar la configuración previa si nginx rechaza el cambio.
had_conf=0
if sudo test -f "$TLS_CONF"; then
  sudo cp "$TLS_CONF" "$tmp/previous.conf"
  had_conf=1
fi
sudo install -m 644 "$tmp/tls.conf" "$TLS_CONF"
if command -v restorecon >/dev/null; then sudo restorecon -R "$TLS_DIR" "$TLS_CONF"; fi
if ! sudo nginx -t; then
  if [ "$had_conf" = 1 ]; then sudo cp "$tmp/previous.conf" "$TLS_CONF";
  else sudo rm -f -- "$TLS_CONF"; fi
  exit 1
fi
sudo systemctl reload nginx
echo "TLS instalado para $TLS_NAME. Certificado público: $TLS_DIR/server.crt"
echo 'Importa ese certificado en tu cliente. HTTP sigue disponible; este script no cambia el firewall.'
