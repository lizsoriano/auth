#!/bin/bash
# Evidencia con curl para Blackboard: cada CAPTURA muestra la petición y su respuesta de uno de los 6 microservicios.
# Imprime una captura a la vez (pantalla limpia) y espera Enter para que tomes la foto.
#
#   Local (Docker):   DEMO_PASSWORD=...  bash e2e/evidencias_curl.sh                     (puertos 15000-15005, e2e/serve_local.sh)
#   VM (por Nginx):   DEMO_PASSWORD=...  VM=http://IP_DE_LA_VM  bash e2e/evidencias_curl.sh
#   Sin pausas:       NOPAUSE=1 ...      Sin limpiar pantalla: NOCLEAR=1 ...
# Usa los usuarios demo-admin@ / demo-staff@ / demo-customer@example.com (se crean con e2e/seed_demo_users.py).
# La contraseña NO se imprime (sale como ********) y los JWT / refresh tokens salen recortados.
# Captura 10 (Redis caído): define REDIS_DOWN_CMD y REDIS_UP_CMD (p. ej. "docker stop lib_redis_local" / "docker start lib_redis_local",
# o en la VM "sudo systemctl stop redis" / "sudo systemctl start redis"); si no, se omite.
set -u
: "${DEMO_PASSWORD:?Define DEMO_PASSWORD (contraseña de los usuarios demo)}"
if [ -n "${VM:-}" ]; then
  B=${VM%/}; LOGIN=$B/auth; BOOKS=$B/soap; USERS=$B/users; AUTHORS=$B/authors; PEDIDOS=$B/pedidos; PAGOS=$B/pagos
else
  P=${BASE_PORT:-15000}; H=http://localhost
  LOGIN=$H:$P; BOOKS=$H:$((P+1)); USERS=$H:$((P+2)); AUTHORS=$H:$((P+3)); PEDIDOS=$H:$((P+4)); PAGOS=$H:$((P+5))
fi
ADMIN=${ADMIN_EMAIL:-demo-admin@example.com}; STAFF=${STAFF_EMAIL:-demo-staff@example.com}; CUST=${CUSTOMER_EMAIL:-demo-customer@example.com}
ISBN=${ISBN:-9780000000006}
T=$(mktemp -d); command -v cygpath >/dev/null 2>&1 && T=$(cygpath -m "$T")  # ruta que entienden curl y python en Windows
JAR=$T/jar_inicial.txt; : > "$JAR"; trap 'rm -rf "$T"' EXIT
PY=python; command -v python >/dev/null 2>&1 || PY=python3

cat > "$T/fmt.py" <<'PYEOF'
import json, sys
body = open(sys.argv[1], encoding="utf-8", errors="replace").read()
keep = int(sys.argv[2])
try:
    data = json.loads(body)
except ValueError:
    print("    " + body[:300].replace("\n", "\n    "))
    sys.exit()
def cut(x):
    if isinstance(x, dict):
        return {k: cut(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        out = [cut(v) for v in x[:keep]]
        return out + ([f"... ({len(x) - keep} más)"] if len(x) > keep else [])
    if isinstance(x, str) and (x.startswith("eyJ") or len(x) > 28 and " " not in x):
        return x[:22] + "...(recortado)"
    return x
print("    " + json.dumps(cut(data), indent=2, ensure_ascii=False).replace("\n", "\n    "))
PYEOF
cat > "$T/jget.py" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for k in sys.argv[2].split("."):
    d = d[int(k)] if isinstance(d, list) else d[k]
print(d)
PYEOF
cat > "$T/claims.py" <<'PYEOF'
import base64, json, sys
p = sys.argv[1].split(".")[1]
c = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
print(f"    alg HS256 · iss={c.get('iss')} · user_id={c['user_id']} · role_id={c['role_id']} ({c.get('role')})")
print(f"    iat={c['iat']}  exp={c['exp']}  →  vigencia = {c['exp'] - c['iat']} s = {(c['exp'] - c['iat']) // 60} minutos")
print(f"    jti={c['jti'][:8]}... (identificador único: sirve para revocar este token)")
PYEOF

cat > "$T/jti.py" <<'PYEOF'
import base64, json, sys
p = sys.argv[1].split(".")[1]
print(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["jti"])
PYEOF
STATUS=""; MS=0
jget() { "$PY" "$T/jget.py" "$T/body" "$1"; }
cap() {
  echo
  if [ -t 1 ] && [ "${NOCLEAR:-}" != 1 ]; then printf '\033[2J\033[H'; fi
  echo "================ CAPTURA $1 - $2 ================"
  [ -n "${3:-}" ] && echo "$3"
}
pause() { if [ -t 0 ] && [ "${NOPAUSE:-}" != 1 ]; then echo; read -r -p "── Toma la captura y pulsa Enter para continuar ── " _; fi; }
call() {  # call MÉTODO URL [TOKEN] [CUERPO_JSON] [ENCABEZADO_EXTRA] [FILAS_A_MOSTRAR]
  local method=$1 url=$2 token=${3:-} body=${4:-} extra=${5:-} keep=${6:-2} sep='?'
  [[ $url == *\?* ]] && sep='&'
  local args=(-s -m 20 -o "$T/body" -D "$T/head" -w '%{time_total}' -X "$method" -b "$JAR" -c "$JAR")
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  [ -n "$extra" ] && args+=(-H "$extra")
  [ -n "$body" ] && args+=(-H "Content-Type: application/json" -d "$body")
  echo; echo "--> curl -X $method $url"
  [ -n "$token" ] && echo "    -H \"Authorization: Bearer ${token:0:20}...(recortado)\""
  [ -n "$extra" ] && echo "    -H \"$extra\""
  [ -n "$body" ] && echo "    -d '$(printf '%s' "${body//$DEMO_PASSWORD/********}" | sed -E 's/("refresh_token":")([^"]{8})[^"]*/...(recortado)/')'"
  local t; t=$(curl "${args[@]}" "$url${sep}format=json")
  STATUS=$(head -1 "$T/head" | tr -d '\r' | cut -d' ' -f2-)
  MS=$("$PY" -c "print(round(float('${t:-0}')*1000))")
  echo "<-- HTTP $STATUS   ($MS ms)"
  grep -i -E '^(idempotent-replay|cache-control):' "$T/head" | tr -d '\r' | sed 's/^/    /'
  "$PY" "$T/fmt.py" "$T/body" "$keep"
}
use_jar() { JAR="$T/jar_${1//[^a-z]/_}.txt"; : > "$JAR"; }   # una sesión (cookie) por usuario
login() {  # login EMAIL  → deja TOKEN y REFRESH
  use_jar "$1"
  call POST "$LOGIN/login" "" "{\"email\":\"$1\",\"password\":\"$DEMO_PASSWORD\"}" "" 2 >/dev/null
  TOKEN=$(jget token); REFRESH=$(jget refresh_token)
}
cat > "$T/rk.py" <<'PYEOF'
import os, sys, redis
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
keys = sorted(r.scan_iter(sys.argv[1]))
for k in keys[:8]:
    print(f"    {k[:58]:58}  TTL {r.ttl(k)} s")
print(f"    ({len(keys)} clave(s) con el patrón {sys.argv[1]})")
PYEOF
redis_keys() {  # redis_keys PATRÓN → local: contenedor lib_serve_app · VM: REDIS_URL + PYREDIS (los exporta deploy/evidencias_curl_vm.sh)
  if docker exec lib_serve_app true 2>/dev/null; then
    docker exec -i lib_serve_app python - "$1" < "$T/rk.py"
  elif [ -n "${REDIS_URL:-}" ] && [ -n "${PYREDIS:-}" ]; then
    "$PYREDIS" "$T/rk.py" "$1"
  else
    echo "    (en la VM:  redis-cli -a \"\$(grep -m1 ^REDIS_URL /opt/auth/services/login/.env | sed -E 's#.*://:([^@]*)@.*#\\1#')\" --no-auth-warning --scan --pattern '$1')"
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
cap 1 "LOGIN → JWT de 20 min + refresh token" "Microservicio LOGIN · POST /login"
use_jar "$CUST"; CUST_JAR=$JAR
call POST "$LOGIN/login" "" "{\"email\":\"$CUST\",\"password\":\"$DEMO_PASSWORD\"}"
TOKEN=$(jget token); REFRESH=$(jget refresh_token); CUST_JWT=$TOKEN
echo; echo "  Claims del JWT (decodificados):"; "$PY" "$T/claims.py" "$TOKEN"
echo; echo "  Sesión y refresh token guardados en Redis (con TTL):"; redis_keys 'session:*'; redis_keys 'refresh:*'; pause

cap 2 "REFRESH con rotación (un solo uso)" "Microservicio LOGIN · POST /token/refresh"
OLD=$REFRESH
call POST "$LOGIN/token/refresh" "" "{\"refresh_token\":\"$OLD\"}"
TOKEN=$(jget token); REFRESH=$(jget refresh_token); CUST_JWT=$TOKEN
echo; echo "  Reusar el refresh token anterior:"
call POST "$LOGIN/token/refresh" "" "{\"refresh_token\":\"$OLD\"}"; pause

cap 3 "BOOKS · caché de Redis (1.ª consulta MISS, 2.ª HIT)" "Microservicio BOOKS · GET /books (público)"
call GET "$BOOKS/books" "" "" "" 1
echo; echo "  Segunda consulta (misma URL):"
call GET "$BOOKS/books" "" "" "" 1
echo; echo "  Claves de caché en Redis:"; redis_keys 'books:*'; pause

cap 4 "BOOKS · seguridad de escrituras (401 / 403 / 200) e invalidación" "Microservicio BOOKS · PATCH /books/{isbn}"
echo "  a) sin JWT:"; call PATCH "$BOOKS/books/$ISBN" "" '{"stock":20}'
echo; echo "  b) con JWT de un customer:"; call PATCH "$BOOKS/books/$ISBN" "$CUST_JWT" '{"stock":20}'
login "$ADMIN"; ADMIN_JWT=$TOKEN
echo; echo "  c) con JWT de admin:"; call PATCH "$BOOKS/books/$ISBN" "$ADMIN_JWT" '{"stock":20}'
echo; echo "  Claves de caché después de escribir (se invalidaron):"; redis_keys 'books:*'; pause

cap 5 "USERS · roles y permisos" "Microservicio USERS · GET /users/me · GET /users"
echo "  customer pide su cuenta:"; call GET "$USERS/users/me" "$CUST_JWT"
echo; echo "  customer intenta listar usuarios:"; call GET "$USERS/users" "$CUST_JWT"
echo; echo "  admin lista usuarios:"; call GET "$USERS/users?limit=3" "$ADMIN_JWT" "" "" 2; pause

cap 6 "AUTHORS · lectura pública y escritura con rol" "Microservicio AUTHORS · GET/POST/DELETE /authors"
echo "  GET público (sin JWT):"; call GET "$AUTHORS/authors?limit=3" "" "" "" 2
echo; echo "  POST sin JWT:"; call POST "$AUTHORS/authors" "" '{"first_name":"Evidencia"}'
login "$STAFF"; STAFF_JWT=$TOKEN
echo; echo "  POST con JWT de staff:"; call POST "$AUTHORS/authors" "$STAFF_JWT" '{"first_name":"Evidencia","last_name":"Curl"}'
AID=$(jget author.author_id)
echo; echo "  DELETE del autor de prueba:"; call DELETE "$AUTHORS/authors/$AID" "$STAFF_JWT"; pause

cap 7 "PEDIDOS · crear pedido (descuenta stock)" "Microservicio PEDIDOS · POST /pedidos · GET /pedidos/{id}"
call POST "$PEDIDOS/pedidos" "$CUST_JWT" "{\"items\":[{\"isbn\":\"$ISBN\",\"quantity\":1}]}"
OID=$(jget order.order_id); TOTAL=$(jget order.total)
echo; echo "  Consultar el pedido:"; call GET "$PEDIDOS/pedidos/$OID" "$CUST_JWT"; pause

cap 8 "PAGOS · idempotencia (no se cobra dos veces)" "Microservicio PAGOS · POST /pagos con Idempotency-Key"
KEY="evidencia-$(date +%s)"
call POST "$PAGOS/pagos" "$CUST_JWT" "{\"order_id\":$OID,\"method\":\"tarjeta\",\"amount\":\"$TOTAL\"}" "Idempotency-Key: $KEY"
PID=$(jget payment.payment_id)
echo; echo "  Reintento con la MISMA Idempotency-Key:"
call POST "$PAGOS/pagos" "$CUST_JWT" "{\"order_id\":$OID,\"method\":\"tarjeta\",\"amount\":\"$TOTAL\"}" "Idempotency-Key: $KEY"
echo; echo "  Intentar modificar un pago:"; call PUT "$PAGOS/pagos/$PID" "$CUST_JWT" '{"status":"x"}'; pause

cap 9 "LOGOUT → el JWT queda revocado en TODOS los servicios" "Microservicio LOGIN · POST /logout  +  Redis jwt:revoked:<jti>"
JAR=$CUST_JAR   # el logout identifica la sesión por su cookie
call POST "$LOGIN/logout" "$CUST_JWT"
echo; echo "  Marca de revocación de ESTE token en Redis (jwt:revoked:<jti>):"; redis_keys "jwt:revoked:$("$PY" "$T/jti.py" "$CUST_JWT")"
echo; echo "  El mismo JWT en USERS:"; call GET "$USERS/users/me" "$CUST_JWT"
echo; echo "  El mismo JWT en PAGOS:"; call GET "$PAGOS/pagos" "$CUST_JWT"; pause

if [ -n "${REDIS_DOWN_CMD:-}" ] && [ -n "${REDIS_UP_CMD:-}" ]; then
  login "$ADMIN"; ADMIN_JWT=$TOKEN
  cap 10 "REDIS CAÍDO: lectura pública sigue, lo protegido falla cerrado" "Se apaga Redis:  $REDIS_DOWN_CMD"
  eval "$REDIS_DOWN_CMD" >/dev/null 2>&1; sleep 2
  echo "  GET /books (público):"; call GET "$BOOKS/books" "" "" "" 1
  echo; echo "  GET /users/me con un JWT válido:"; call GET "$USERS/users/me" "$ADMIN_JWT"
  echo; echo "  POST /login:"; call POST "$LOGIN/login" "" "{\"email\":\"$ADMIN\",\"password\":\"$DEMO_PASSWORD\"}"
  echo; echo "  GET $BOOKS/health:"; call GET "$BOOKS/health"
  eval "$REDIS_UP_CMD" >/dev/null 2>&1; sleep 2; echo; echo "  (Redis encendido de nuevo)"; pause
else
  echo; echo "(Captura 10 omitida: define REDIS_DOWN_CMD y REDIS_UP_CMD para apagar y encender Redis.)"
fi
echo; echo "Fin de las capturas."
