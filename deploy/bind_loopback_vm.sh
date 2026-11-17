#!/bin/bash
# Deja los microservicios escuchando SOLO en 127.0.0.1 (regla de la arquitectura: apps -> gateway; servicios en loopback).
# En la VM algunas units de systemd traian `-b 0.0.0.0:PUERTO`: cualquier regla de firewall que abriera ese puerto los
# expondria sin pasar por el gateway. Este script cambia 0.0.0.0 por 127.0.0.1 en las units de login, soap, users, authors,
# pedidos y pagos (con respaldo .bak-loopback), recarga y reinicia. NO toca /library (monolito, puerto 3000).
# Idempotente.  Ejecutar en la VM:   sudo bash deploy/bind_loopback_vm.sh     (revertir: restaurar los .bak-loopback)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "ERROR: ejecuta con sudo" >&2; exit 1; }
changed=0
for unit in login soap users authors pedidos pagos; do
  f=/etc/systemd/system/$unit.service
  [ -f "$f" ] || { echo "  $unit: sin unit (se omite)"; continue; }
  if grep -q "0\.0\.0\.0:" "$f"; then
    cp -n "$f" "$f.bak-loopback"
    sed -i -E '/^ExecStart=/ s/0\.0\.0\.0:/127.0.0.1:/' "$f"
    echo "  $unit: ahora escucha en 127.0.0.1"; changed=1
  else
    echo "  $unit: ya estaba en loopback"
  fi
done
if [ "$changed" = 1 ]; then
  systemctl daemon-reload
  for unit in login soap users authors pedidos pagos; do [ -f /etc/systemd/system/$unit.service ] && systemctl restart "$unit"; done
  sleep 2
fi
echo; echo "Sockets de los servicios:"
ss -ltn | awk '$4 ~ /:(5000|5001|5002|5003|5004|5005)$/ {print "  " $4}' | sort
exposed=$(ss -ltn | awk '$4 ~ /^(0\.0\.0\.0|\[::\]|\*):(5000|5001|5002|5003|5004|5005)$/ {print $4}')
[ -z "$exposed" ] && echo "OK: ningun servicio escucha fuera de 127.0.0.1" || { echo "AVISO: siguen expuestos: $exposed"; exit 1; }
