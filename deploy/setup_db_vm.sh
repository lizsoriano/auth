#!/bin/bash
# Aplica en la VM las migraciones del servicio login sobre library_db y deja el servicio en marcha.
#
#   bash /opt/auth/deploy/setup_db_vm.sh
#
# Pide POR TECLADO (no se muestran ni se guardan) la contraseña de `postgres` y la de `library_user`.
# Antes de migrar hace un respaldo y una "foto" de los datos existentes; despues compara: si algo de
# books/usuarios cambiara, avisa. La contraseña del rol login_service_user se genera aqui (aleatoria) y
# solo se escribe en /opt/auth/services/login/.env (permisos 600).
set -uo pipefail

REPO=${REPO:-/opt/auth}
DB=${DB:-library_db}
HOST=${PGHOST:-localhost}
LIB_USER=${LIB_USER:-library_user}
MIG=$REPO/data/migrations
ENVFILE=$REPO/services/login/.env
BACKUP_DIR=${BACKUP_DIR:-$HOME/backups}

say(){ printf '\n== %s\n' "$*"; }
die(){ printf '\nERROR: %s\n' "$*" >&2; exit 1; }
ask(){ # ask VAR "pregunta": solo pregunta si la variable no viene ya definida (uso en pruebas)
  if [ -z "${!1:-}" ]; then read -r -s -p "$2" "$1"; echo; fi
  [ -n "${!1:-}" ] || die "contraseña vacia"; export "$1"
}
as_postgres(){ PGPASSWORD="$POSTGRES_PW" psql -h "$HOST" -U postgres -d "$DB" -v ON_ERROR_STOP=1 -q "$@"; }
as_library(){  PGPASSWORD="$LIBRARY_PW"  psql -h "$HOST" -U "$LIB_USER" -d "$DB" -v ON_ERROR_STOP=1 -q "$@"; }

[ -d "$MIG" ] || die "no encuentro $MIG (¿clonaste el repo en $REPO?)"
[ -f "$ENVFILE" ] || die "no existe $ENVFILE"
command -v psql >/dev/null && command -v pg_dump >/dev/null || die "faltan psql/pg_dump (sudo dnf install -y postgresql)"

say "Contraseñas (se piden aqui; no se muestran)"
ask POSTGRES_PW "  Contraseña del usuario 'postgres': "
ask LIBRARY_PW  "  Contraseña de '$LIB_USER': "

say "1) Comprobando conexion y permisos"
as_postgres -tAc "select 'postgres: ok'" || die "la contraseña de postgres no funciona"
as_library  -tAc "select '$LIB_USER: ok'" || die "la contraseña de $LIB_USER no funciona"
OWNER=$(as_library -tAc "select tableowner from pg_tables where schemaname='public' and tablename='users'")
[ "$OWNER" = "$LIB_USER" ] || die "la tabla users no pertenece a $LIB_USER (dueño: '${OWNER:-no existe}'); las migraciones deben correr como el dueño"
echo "users pertenece a $LIB_USER: ok"

snapshot(){ # foto de los datos EXISTENTES (solo columnas que ya existian antes del login); un -c por consulta
  as_library -tA     -c "select 'users_cols', count(*), coalesce(md5(string_agg(user_id||'|'||email||'|'||password_hash||'|'||display_name||'|'||is_admin||'|'||is_active, ',' order by user_id)),'') from users"     -c "select 'books', count(*), coalesce(md5(string_agg(book_id||'|'||isbn||'|'||title||'|'||price||'|'||stock, ',' order by book_id)),'') from books"     -c "select 'authors', count(*), '' from authors"     -c "select 'book_authors', count(*), '' from book_authors"     -c "select 'book_concepts', count(*), '' from book_concepts"     -c "select 'book_images', count(*), '' from book_images"
}

say "2) Respaldo previo"
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
BK="$BACKUP_DIR/${DB}_$(date +%Y%m%d_%H%M%S).sql"
# como postgres: las tablas de soap (clasificadores...) pertenecen a postgres y library_user no puede leerlas todas
PGPASSWORD="$POSTGRES_PW" pg_dump -h "$HOST" -U postgres "$DB" > "$BK" || die "el respaldo fallo; no se migra nada"
chmod 600 "$BK"; [ -s "$BK" ] || die "el respaldo quedo vacio; no se migra nada"
echo "respaldo: $BK ($(du -h "$BK" | cut -f1))"

say "3) Foto de los datos ANTES de migrar"
snapshot > /tmp/login_before.$$ || die "no se pudo tomar la foto"
cat /tmp/login_before.$$ | sed 's/^/   /'

say "4) Rol del servicio (login_service_user)"
if grep -q 'login_service_user:PENDIENTE@' "$ENVFILE"; then
  LOGIN_PW=$(openssl rand -hex 24); export LOGIN_PW
  { echo '\set login_password `printenv LOGIN_PW`'
    cat "$MIG/000_create_login_role.sql"
    echo "ALTER ROLE login_service_user PASSWORD :'login_password';"; } | as_postgres || die "no se pudo crear/actualizar el rol"
  NEW_PW=1; echo "rol listo con contraseña nueva aleatoria (solo se guardara en .env)"
else
  [ "$(as_postgres -tAc "select count(*) from pg_roles where rolname='login_service_user'")" = 1 ]     || die "el .env ya tiene una contraseña pero el rol login_service_user no existe: pon PENDIENTE en DATABASE_URL para regenerarla"
  NEW_PW=0; echo "el rol ya existe y el .env ya tiene contraseña: se conserva"
fi

say "5) Migraciones (aditivas e idempotentes, como $LIB_USER)"
for f in 001_login_service 002_login_email_verification 003_login_service_grants; do
  as_library -f "$MIG/$f.sql" || die "fallo $f.sql (cada archivo es una transaccion: no queda nada a medias)"
  echo "$f.sql: ok"
done

say "6) Foto DESPUES: los datos existentes no deben cambiar"
snapshot > /tmp/login_after.$$ || die "no se pudo tomar la foto posterior"
if diff -q /tmp/login_before.$$ /tmp/login_after.$$ >/dev/null; then echo "IDENTICA a la de antes: books, usuarios y catalogo intactos"
else echo "¡DIFERENCIAS!"; diff /tmp/login_before.$$ /tmp/login_after.$$; die "revisa antes de continuar (respaldo en $BK)"; fi
rm -f /tmp/login_before.$$ /tmp/login_after.$$
echo "cuentas existentes ya verificadas: $(as_library -tAc "select count(*) filter (where email_verified_at is not null) || ' de ' || count(*) from users")"

if [ "$NEW_PW" = 1 ]; then
  say "7) Guardando la cadena de conexion en $ENVFILE"
  sed -i "s#^DATABASE_URL=.*#DATABASE_URL=postgresql://login_service_user:${LOGIN_PW}@localhost:5432/${DB}#" "$ENVFILE"
  chmod 600 "$ENVFILE"; echo ".env actualizado (permisos $(stat -c %a "$ENVFILE"))"
fi
LOGIN_PW=$(sed -n 's#^DATABASE_URL=postgresql://login_service_user:\([^@]*\)@.*#\1#p' "$ENVFILE")

say "8) El rol del servicio: lo permitido y lo prohibido"
PGPASSWORD="$LOGIN_PW" psql -h "$HOST" -U login_service_user -d "$DB" -tAc "select 'conecta y lee users: ok ('||count(email)||' cuentas)' from users" || die "login_service_user no puede conectar"
for q in "select is_admin from users" "select * from books" "delete from users"; do
  if PGPASSWORD="$LOGIN_PW" psql -h "$HOST" -U login_service_user -d "$DB" -qtAc "$q" >/dev/null 2>&1
  then echo "  ¡ALERTA! permitido: $q"; else echo "  denegado (correcto): $q"; fi
done

if [ "${SKIP_SERVICE:-0}" != 1 ]; then
  say "9) Arrancando el servicio"
  sudo systemctl enable --now login && sleep 4
  echo "login.service: $(systemctl is-active login)"
  curl -s "localhost:5000/health?format=json"; echo
fi
say "LISTO. Respaldo: $BK"
