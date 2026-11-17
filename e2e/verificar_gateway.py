"""Recorrido completo de Library A TRAVÉS del API Gateway (login -> perfil -> catálogo -> pedido -> pago -> rastreo).

Uso (con la pila local de e2e/serve_local.sh, el rastreo en :5900 y el gateway en :8080):
    LIBRARY_DEMO_USER=demo-customer@example.com LIBRARY_DEMO_PASSWORD=... python e2e/verificar_gateway.py
Opcional: GW=http://127.0.0.1:8081 (Nginx delante del gateway) y HEALTH=/gateway/health.
Las credenciales salen SOLO del entorno; nunca se imprimen. Necesita: pip install requests websocket-client
"""
import json
import os
import sys
import time
import uuid

import requests
import websocket

GW = os.environ.get("GW", "http://127.0.0.1:8080").rstrip("/")
HEALTH = os.environ.get("HEALTH", "/health")
ok = True


def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("OK    " if cond else "FALLA "), name, extra)


def call(method, path, **kw):
    """Igual que la app Java: los servicios responden XML por omisión, así que piden JSON con ?format=json."""
    params = {} if path.startswith("/gps/") else {"format": "json"}
    params.update(kw.pop("params", None) or {})
    return requests.request(method, GW + path, params=params, timeout=15, **kw)


user, password = os.environ.get("LIBRARY_DEMO_USER"), os.environ.get("LIBRARY_DEMO_PASSWORD")
if not user or not password:
    sys.exit("Faltan LIBRARY_DEMO_USER y LIBRARY_DEMO_PASSWORD en el entorno.")

r = call("POST", "/auth/login", json={"email": user, "password": password})
check("login por /auth/login", r.status_code == 200, f"-> {r.status_code}")
body = r.json()
token = body.get("access_token") or body.get("token")
auth = {"Authorization": f"Bearer {token}"}

check("perfil por /users (con JWT)", call("GET", "/users/users/me", headers=auth).status_code == 200)
check("sin token: 401 del servicio", call("GET", "/users/users/me").status_code == 401)
check("token falso: 401 del servicio",
      call("GET", "/users/users/me", headers={"Authorization": "Bearer falso.falso.falso"}).status_code == 401)

r = call("GET", "/soap/books")
check("catálogo por /soap/books", r.status_code == 200)
books = r.json()
books = books if isinstance(books, list) else books.get("books", [])
book = next(b for b in books if (b.get("stock") or 0) > 0)
check("autores por /authors", call("GET", "/authors/authors").status_code == 200)

r = call("POST", "/pedidos/pedidos", headers=auth, json={"items": [{"isbn": book["isbn"], "quantity": 1}]})
check("crear pedido por /pedidos", r.status_code in (200, 201), f"-> {r.status_code}")
order = r.json().get("order", r.json())
order_id, total = order.get("id") or order.get("order_id"), order.get("total")

r = call("POST", "/pagos/pagos", headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
         json={"order_id": order_id, "amount": total, "method": "tarjeta"})
check("pago por /pagos con Idempotency-Key", r.status_code in (200, 201), f"-> {r.status_code}")

code = f"LIB-MTY-{time.strftime('%Y')}-{int(order_id):06d}"
check("rastreo REST por /gps/tracking", call("GET", f"/gps/tracking/{code}", headers=auth).status_code == 200)

ws = websocket.create_connection(GW.replace("http", "ws", 1) + "/gps/ws/tracking", timeout=10)
ws.send(json.dumps({"type": "auth", "token": token, "code": code}))
first = json.loads(ws.recv())
check("WebSocket por /gps/ws/tracking: snapshot", first.get("type") == "snapshot")
second = json.loads(ws.recv())
check("WebSocket: update de posición", second.get("type") == "update", f"-> {second.get('status')}")
ws.close()

health = requests.get(GW + HEALTH, timeout=10).json()
print("health:", health)
check("todos los servicios arriba", health.get("status") == "ok")
print("RESULTADO:", "TODO OK" if ok else "HAY FALLAS")
sys.exit(0 if ok else 1)
