# gateway — API Gateway de Library (Flask + Flask-Sock)

Es la **única puerta** hacia los microservicios. Las apps (Java, Tkinter, Electron) hablan solo con el gateway; los servicios y PostgreSQL escuchan únicamente en `127.0.0.1`.

```
 App Java (JavaFX) ─┐
 App Python (Tk)  ──┼─►  Nginx :80 / :443  ──►  API Gateway 127.0.0.1:8080  ──┬─►  login    :5000   /auth
 App Electron (XML) ┘   (única puerta pública,     (enruta por prefijo,         ├─►  books    :5001   /soap
                         por IP, sin dominio)       reenvía JWT, WebSocket)     ├─►  users    :5002   /users
                                                                                ├─►  authors  :5003   /authors
                                                                                ├─►  pedidos  :5004   /pedidos
                                                                                ├─►  pagos    :5005   /pagos
                                                                                └─►  gps      :5900   /gps  (REST + WebSocket)
                                                                      PostgreSQL y Redis: solo los usan los servicios
```

**Reglas de la arquitectura**

1. Las apps → solo el gateway. Nginx reenvía todo a `127.0.0.1:8080` (`deploy/nginx-gateway-proxy.conf`).
2. Los servicios (y el propio gateway) en `127.0.0.1`: ningún puerto interno se abre en el firewall de GCP.
3. La base de datos es solo para los servicios: el gateway no se conecta a PostgreSQL ni a Redis.

## Qué hace (y qué no)

| Hace | No hace |
|---|---|
| Enruta por prefijo y **recorta el prefijo** (`/pedidos/pedidos` → `GET /pedidos` en el servicio) | Reimplementar reglas de negocio |
| Reenvía método, query, cuerpo y encabezados sin cambios: `Authorization: Bearer`, `Idempotency-Key`, `Cookie` / `Set-Cookie` | **Validar el JWT**: cada servicio decide a quién atiende; un token falso recibe el `401` del servicio, no uno inventado |
| Proxy de **WebSocket** del rastreo: `/gps/ws/tracking` (el JWT va en el primer mensaje, no en la URL) | Registrar tokens, cuerpos ni *query strings* en el log |
| Añade `X-Request-ID` (para seguir una petición) y `X-Forwarded-*`; los del cliente se ignoran salvo que vengan del Nginx local | Rate limiting ni caché (ver «Límites») |
| Reescribe `Location` de redirecciones con el prefijo público | |
| Errores en JSON: `502` servicio caído, `504` servicio lento (30 s), `413` cuerpo > 1 MiB, `404` prefijo desconocido | |
| `GET /health`: estado `up/degraded/down` de cada servicio, sin revelar direcciones internas | |

Los **contratos de los servicios no cambian** y los prefijos son los de siempre (`/auth`, `/soap`, `/users`, `/authors`, `/pedidos`, `/pagos`, `/gps`), así que las apps solo cambian de dirección base, no de código. `/library` (el monolito que sirve las portadas) sigue directo en Nginx.

## Ejecutar en local

```bash
cd services/gateway
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt     # Linux/macOS: .venv/bin/python
.venv/Scripts/python app.py                                      # 127.0.0.1:8080
```

Por defecto apunta a `127.0.0.1:5000…5005` y `:5900`. Con la pila local de `e2e/serve_local.sh` (puertos 15000–15005):

```bash
AUTH_URL=http://127.0.0.1:15000 SOAP_URL=http://127.0.0.1:15001 USERS_URL=http://127.0.0.1:15002 \
AUTHORS_URL=http://127.0.0.1:15003 PEDIDOS_URL=http://127.0.0.1:15004 PAGOS_URL=http://127.0.0.1:15005 \
GPS_URL=http://127.0.0.1:5900 python app.py
curl http://127.0.0.1:8080/health
```

Variables (todas opcionales, ver `.env.example`): `<NOMBRE>_URL` por servicio (`AUTH_URL`, `SOAP_URL`, `USERS_URL`, `AUTHORS_URL`, `PEDIDOS_URL`, `PAGOS_URL`, `GPS_URL`), `GATEWAY_HOST` (127.0.0.1), `GATEWAY_PORT` (8080), `GATEWAY_CONNECT_TIMEOUT` (3 s), `GATEWAY_READ_TIMEOUT` (30 s), `GATEWAY_MAX_BODY_BYTES` (1 MiB), `GATEWAY_LOG_LEVEL`. El gateway **no lleva secretos**.

Si los servicios corren como contenedores o *pods* en lugar de procesos, solo cambian esas URL (`PEDIDOS_URL=http://servicio-pedidos:5004`). Hay un `Dockerfile` opcional.

## Pruebas

```bash
.venv/Scripts/python -m pytest -q     # 30 pruebas: enrutamiento, encabezados, cookies, redirecciones, 413/502/504, health y WebSocket
```

Usan servicios falsos en puertos libres. Además, `e2e/verificar_gateway.py` recorre el flujo real (login → perfil → catálogo → pedido → pago → rastreo REST y WebSocket) **solo a través del gateway** contra la pila local.

## Despliegue en la VM (sin dominio)

`sudo bash deploy/setup_gateway_vm.sh` (desde `/opt/auth`): instala el venv, la unit `gateway.service` (gunicorn, 1 proceso con 200 hilos, `127.0.0.1:8080`), instala `library-gateway.conf` en Nginx, aparta los `.conf` por servicio a `/etc/nginx/default.d.gateway-backup/` y comprueba `/gateway/health`. Si `nginx -t` falla restaura todo; `--rollback` vuelve a los `.conf` anteriores. Los puertos de cada servicio se **leen de su unit de systemd** y se escriben en el `.env` del gateway (la VM puede usar otros que el repo; por ejemplo users 5004, authors 5005, pedidos 5003, pagos 5002). `deploy/bind_loopback_vm.sh` deja además a los servicios escuchando solo en `127.0.0.1`. Nginx atiende por **IP** (no hace falta dominio); TLS con `deploy/setup_tls_vm.sh` sigue funcionando igual. *Este despliegue todavía no se ha ejecutado en la VM* (la facturación del proyecto de GCP está desactivada); sí se probó localmente la cadena completa Nginx → gateway → servicios, incluido el WebSocket.

## Límites conocidos

- Un solo proceso y estado en memoria: el gateway no es alta disponibilidad. Si se cae, Nginx responde `502` hasta que systemd lo reinicia (`Restart=on-failure`).
- Sin *rate limiting*, caché ni autenticación propia: se podrían agregar aquí sin tocar los servicios.
- Cada WebSocket de rastreo ocupa un hilo del gateway y otro del servicio mientras dura la entrega.
- Un cuerpo de petición mayor a 1 MiB se rechaza con `413` (Nginx ya limitaba a 1 MiB).
