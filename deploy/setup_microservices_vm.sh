#!/bin/bash
# Despliega en la VM TODO lo del ejercicio de microservicios + Redis. Idempotente (se puede repetir).
#
#   cd /opt/auth && git pull && bash deploy/setup_microservices_vm.sh
#
# Qué hace, en este orden (si algo falla se detiene ANTES de tocar los servicios):
#   1. Pide POR TECLADO (no se muestran ni se guardan) la contraseña de `postgres` y la de `library_user`.
#   2. Respaldo de library_db + "foto" de books/users, y al final compara: si algo existente cambió, avisa.
#   3. Migraciones 006-011 (roles, funciones de Users/Authors/Pedidos/Pagos, REVOKE de PUBLIC en books).
#   4. Redis: contraseña (requirepass), AOF (la lista de revocación sobrevive un reinicio), maxmemory y noeviction.
#   5. Código: venv + dependencias + paquete compartido (library_common) de login, books y los 4 servicios nuevos.
#   6. .env de cada servicio (permisos 600): el MISMO JWT_SECRET_KEY en todos y la REDIS_URL común.
#   7. systemd (con After/Wants=redis.service) y proxy de nginx (/users/ /authors/ /pedidos/ /pagos/).
#   8. Comprobación de /health de los 6 servicios.
# Las contraseñas de los roles de BD y la de Redis se GENERAN aquí (aleatorias) y solo se escriben en los .env y en
# redis.conf; nunca se imprimen ni quedan en el historial.
set -uo pipefail

REPO=${REPO:-/opt/auth}
SOAP_DIR=${SOAP_DIR:-/opt/library_soap_service}
DB=${DB:-library_db}
HOST=${PGHOST:-localhost}
LIB_USER=${LIB_USER:-library_user}
MIG=$REPO/data/migrations
BACKUP_DIR=${BACKUP_DIR:-$HOME/backups}
REDIS_CONF=${REDIS_CONF:-/etc/redis/redis.conf}
NEW_SERVICES="users authors pedidos pagos"
declare -A PORT=([login]=5000 [soap]=5001 [users]=5002 [authors]=5003 [pedidos]=5004 [pagos]=5005)
declare -A ROLE=([users]=users_service_user [authors]=authors_service_user [pedidos]=pedidos_service_user [pagos]=pagos_service_user)

say(){ printf '\n== %s\n' "$*"; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
ask(){ if [ -z "${!1:-}" ]; then read -r -s -p "$2" "$1"; echo; fi; [ -n "${!1:-}" ] || die "contraseña vacia"; export "$1"; }
as_postgres(){ PGPASSWORD="$POSTGRES_PW" psql -h "$HOST" -U postgres -d "$DB" -v ON_ERROR_STOP=1 -q "$@"; }
as_library(){  PGPASSWORD="$LIBRARY_PW"  psql -h "$HOST" -U "$LIB_USER" -d "$DB" -v ON_ERROR_STOP=1 -q "$@"; }
envget(){ [ -f "$1" ] && grep -m1 "^$2=" "$1" | cut -d= -f2- || true; }
envset(){ # envset ARCHIVO VARIABLE  (el VALOR viaja por la variable de entorno V: no aparece en `ps`)
  python3 - "$1" "$2" <<'PY'
import os, pathlib, re, sys
path, var = sys.argv[1:3]
value = os.environ["V"]
p = pathlib.Path(path)
lines = p.read_text().splitlines() if p.exists() else []
out, done = [], False
for line in lines:
    if re.match(rf"^{re.escape(var)}=", line):
        if not done:
            out.append(f"{var}={value}")
            done = True
    else:
        out.append(line)
if not done:
    out.append(f"{var}={value}")
p.write_text("\n".join(out) + "\n")
PY
}
envdel(){ [ -f "$1" ] && sed -i "/^$2=/d" "$1" || true; }
urlpass(){ python3 -c 'import sys,urllib.parse as u; print(u.urlparse(sys.argv[1]).password or "")' "$1"; }

for c in psql pg_dump python3 openssl curl redis-cli sudo; do command -v "$c" >/dev/null || die "falta el comando $c"; done
for f in 006_roles 007_service_db_roles 008_users_authors_functions 009_pedidos 010_pagos 011_revoke_public_execute_books_functions; do
  [ -f "$MIG/$f.sql" ] || die "no encuentro $MIG/$f.sql (¿hiciste git pull en $REPO?)"
done
[ -d "$REPO/services/shared" ] || die "no encuentro $REPO/services/shared (¿hiciste git pull?)"
[ -d "$SOAP_DIR" ] || die "no existe $SOAP_DIR (donde corre books/soap.service)"
sudo -n true 2>/dev/null || die "este script necesita sudo sin contraseña (como el resto de los de deploy/)"

say "Contraseñas (se piden aqui; no se muestran)"
ask POSTGRES_PW "  Contraseña del usuario 'postgres': "
ask LIBRARY_PW  "  Contraseña de '$LIB_USER': "

say "1) Comprobando conexión y permisos"
as_postgres -tAc "select 'postgres: ok'" || die "la contraseña de postgres no funciona"
as_library  -tAc "select '$LIB_USER: ok'" || die "la contraseña de $LIB_USER no funciona"
OWNER=$(as_library -tAc "select tableowner from pg_tables where schemaname='public' and tablename='users'")
[ "$OWNER" = "$LIB_USER" ] || die "la tabla users no pertenece a $LIB_USER (dueño: '${OWNER:-no existe}')"
[ "$(as_library -tAc "select count(*) from pg_roles where rolname='login_service_user'")" = 1 ] || die "falta el rol login_service_user: aplica antes deploy/setup_db_vm.sh"

snapshot(){ as_library -tA \
  -c "select 'users', count(*), coalesce(md5(string_agg(user_id||'|'||email||'|'||password_hash||'|'||display_name||'|'||is_admin||'|'||is_active, ',' order by user_id)),'') from users" \
  -c "select 'books', count(*), coalesce(md5(string_agg(book_id||'|'||isbn||'|'||title||'|'||price||'|'||stock, ',' order by book_id)),'') from books" \
  -c "select 'authors', count(*), coalesce(md5(string_agg(author_id||'|'||first_name||'|'||coalesce(last_name,''), ',' order by author_id)),'') from authors" \
  -c "select 'book_authors', count(*), '' from book_authors" -c "select 'book_images', count(*), '' from book_images"; }

say "2) Respaldo previo y foto de los datos"
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
BK="$BACKUP_DIR/${DB}_micro_$(date +%Y%m%d_%H%M%S).sql"
PGPASSWORD="$POSTGRES_PW" pg_dump -h "$HOST" -U postgres "$DB" > "$BK" || die "el respaldo falló; no se migra nada"
chmod 600 "$BK"; [ -s "$BK" ] || die "el respaldo quedó vacío; no se migra nada"
echo "respaldo: $BK ($(du -h "$BK" | cut -f1))"
snapshot > /tmp/micro_before.$$ || die "no se pudo tomar la foto"; sed 's/^/   /' /tmp/micro_before.$$

say "3) Contraseñas de los roles de BD (se reutilizan las de los .env existentes; si no hay, se generan)"
for s in $NEW_SERVICES; do
  pw=$(urlpass "$(envget "$REPO/services/$s/.env" DATABASE_URL)")
  case "$pw" in ""|CAMBIAR) pw=$(openssl rand -hex 24);; esac
  export "PW_$s=$pw"
done

say "4) Migraciones 006-011"
as_library -f "$MIG/006_roles.sql" || die "falló 006"
{ echo '\set users_password `printenv PW_users`'; echo '\set authors_password `printenv PW_authors`'
  echo '\set pedidos_password `printenv PW_pedidos`'; echo '\set pagos_password `printenv PW_pagos`'
  cat "$MIG/007_service_db_roles.sql"
  for s in $NEW_SERVICES; do echo "ALTER ROLE ${ROLE[$s]} PASSWORD :'${s}_password';"; done; } | as_postgres || die "falló 007"
for f in 008_users_authors_functions 009_pedidos 010_pagos; do as_library -f "$MIG/$f.sql" || die "falló $f"; done
OUT011=$(as_postgres -f "$MIG/011_revoke_public_execute_books_functions.sql" 2>&1) || { echo "$OUT011"; die "falló 011"; }
echo "$OUT011" | grep -i "no privileges" && echo "AVISO: algunas funciones no se pudieron revocar (¿corriste 011 como postgres?)"
echo "migraciones aplicadas"
snapshot > /tmp/micro_after.$$ || die "no se pudo tomar la foto posterior"
if diff -q /tmp/micro_before.$$ /tmp/micro_after.$$ >/dev/null; then echo "datos existentes (users/books/authors/relaciones): IDÉNTICOS antes y después"
else echo "AVISO: cambió algo existente:"; diff /tmp/micro_before.$$ /tmp/micro_after.$$; fi
rm -f /tmp/micro_before.$$ /tmp/micro_after.$$

say "5) Redis protegido (requirepass, AOF, maxmemory, noeviction)"
REDIS_PW=""
for f in "$REPO/services/login/.env" "$SOAP_DIR/.env" $(for s in $NEW_SERVICES; do echo "$REPO/services/$s/.env"; done); do
  [ -n "$REDIS_PW" ] && break
  p=$(urlpass "$(envget "$f" REDIS_URL)"); case "$p" in ""|CAMBIAR) ;; *) REDIS_PW=$p;; esac
done
[ -n "$REDIS_PW" ] || REDIS_PW=$(openssl rand -hex 24)
export REDIS_PW
sudo cp -n "$REDIS_CONF" "$REDIS_CONF.antes_de_library" 2>/dev/null || true
sudo REDIS_CONF="$REDIS_CONF" REDIS_PW="$REDIS_PW" python3 - <<'PY' || die "no se pudo editar $REDIS_CONF"
import os, re, pathlib
path = pathlib.Path(os.environ["REDIS_CONF"])
wanted = {"requirepass": os.environ["REDIS_PW"], "appendonly": "yes", "appendfsync": "everysec",
          "maxmemory": "128mb", "maxmemory-policy": "noeviction"}
lines = path.read_text().splitlines()
seen, out = set(), []
for line in lines:
    key = line.split(None, 1)[0] if line.strip() and not line.lstrip().startswith("#") else None
    if key in wanted:
        if key not in seen:
            out.append(f"{key} {wanted[key]}")
            seen.add(key)
    else:
        out.append(line)
out += [f"{k} {v}" for k, v in wanted.items() if k not in seen]
path.write_text("\n".join(out) + "\n")
PY
sudo systemctl restart redis || die "redis no reinició (revisa: journalctl -u redis)"
sleep 1
[ "$(REDISCLI_AUTH="$REDIS_PW" redis-cli ping 2>/dev/null)" = PONG ] || die "Redis no responde con la contraseña nueva"
case "$(redis-cli ping 2>&1)" in *NOAUTH*) echo "Redis: exige contraseña (sin ella responde NOAUTH)";; *) die "Redis sigue aceptando conexiones SIN contraseña";; esac
echo "Redis: requirepass + AOF + maxmemory 128mb/noeviction aplicados (solo escucha en loopback)"
REDIS_URL="redis://:${REDIS_PW}@127.0.0.1:6379/0"

say "6) Código y entornos virtuales"
SHARED=$REPO/services/shared
venv(){ # venv DIRECTORIO
  [ -d "$1/.venv" ] || python3 -m venv "$1/.venv" || die "no se pudo crear el venv de $1"
  "$1/.venv/bin/pip" install -q --upgrade pip >/dev/null 2>&1
  "$1/.venv/bin/pip" install -q -r "$1/requirements.txt" || die "pip falló en $1"
  "$1/.venv/bin/pip" install -q --upgrade --force-reinstall --no-deps "$SHARED" || die "no se pudo instalar library_common en $1"
}
for s in login $NEW_SERVICES; do echo "   $s"; venv "$REPO/services/$s"; done
echo "   soap (books) -> $SOAP_DIR"
tar -C "$REPO/services/soap" --exclude=.env --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache -cf - . | tar -C "$SOAP_DIR" -xf - \
  || die "no se pudo copiar books a $SOAP_DIR"
venv "$SOAP_DIR"

say "7) Archivos .env (600): mismo JWT_SECRET_KEY en los 6 servicios y la REDIS_URL común"
JWT=$(envget "$REPO/services/login/.env" JWT_SECRET_KEY)
[ ${#JWT} -ge 32 ] || JWT=$(envget "$REPO/services/login/.env" JWT_SECRET)   # el secreto que ya usaba login (y books) se conserva
[ ${#JWT} -ge 32 ] || JWT=$(openssl rand -hex 32)
for s in login $NEW_SERVICES soap; do
  case $s in soap) dir=$SOAP_DIR;; *) dir=$REPO/services/$s;; esac
  f=$dir/.env
  [ -f "$f" ] || cp "$dir/.env.example" "$f" || die "no existe $dir/.env.example"
  chmod 600 "$f"
  V="$JWT" envset "$f" JWT_SECRET_KEY
  V="$REDIS_URL" envset "$f" REDIS_URL
  case $s in
    login) envdel "$f" JWT_SECRET; envdel "$f" JWT_EXPIRATION_HOURS
           V=20 envset "$f" JWT_EXPIRATION_MINUTES; V=24 envset "$f" REFRESH_TOKEN_TTL_HOURS;;
    soap)  envdel "$f" JWT_SECRET;;
    *)     dburl="postgresql://${ROLE[$s]}:$(printenv "PW_$s")@localhost:5432/$DB"
           V="$dburl" envset "$f" DATABASE_URL; V="${PORT[$s]}" envset "$f" FLASK_PORT;;
  esac
done
echo "listo (los valores secretos no se muestran)"

say "8) systemd y nginx"
for u in login soap $NEW_SERVICES; do sudo cp "$REPO/deploy/$u.service" "/etc/systemd/system/$u.service" || die "no se pudo copiar $u.service"; done
sudo systemctl daemon-reload
for u in $NEW_SERVICES; do sudo systemctl enable "$u" >/dev/null 2>&1; done
for u in login soap $NEW_SERVICES; do sudo systemctl restart "$u" || echo "AVISO: $u no arrancó (journalctl -u $u -n 30)"; done
sudo cp "$REPO/deploy/nginx-microservices-proxy.conf" /etc/nginx/default.d/library-microservices.conf
NGX=$(sudo nginx -t 2>&1) || { echo "$NGX"; die "nginx -t falló: revisa /etc/nginx/default.d/library-microservices.conf"; }
sudo systemctl reload nginx || die "nginx no recargó"

say "9) Comprobación"
sleep 3
ok=1
for s in login soap $NEW_SERVICES; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT[$s]}/health?format=json")
  printf '   %-8s :%s  /health -> %s\n' "$s" "${PORT[$s]}" "$code"; [ "$code" = 200 ] || ok=0
done
for p in users authors pedidos pagos; do
  printf '   nginx /%s/health -> %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1/$p/health?format=json")"
done
[ "$ok" = 1 ] && echo "Todo arriba. Siguiente: bash $REPO/deploy/evidencias_microservicios.sh" || echo "Algún servicio no respondió 200: journalctl -u <servicio> -n 40"
