"""Comprueba contra los servicios REALES (local) que el rastreo respeta la sesión y el dueño del pedido.

Uso (la contraseña de las cuentas demo viene del entorno; nunca va en el archivo):
    set LIBRARY_DEMO_PASSWORD=...        &  python verificar_autorizacion.py
Requiere: servicios en localhost:15000-15005, servidor de rastreo en 127.0.0.1:5900 y `pip install websocket-client`.
"""
import json
import os
import urllib.error
import urllib.request
import uuid

import websocket

PW = os.environ["LIBRARY_DEMO_PASSWORD"]
LOGIN, USERS, PEDIDOS, PAGOS, GPS = ("http://localhost:15000", "http://localhost:15002", "http://localhost:15004",
                                      "http://localhost:15005", "http://127.0.0.1:5900")


def call(method, url, token=None, body=None, headers=None):
    h = {"Accept": "application/json", **(headers or {})}
    if token:
        h["Authorization"] = "Bearer " + token
    if body is not None:
        h["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def login(mail):
    return call("POST", LOGIN + "/login?format=json", None, {"email": mail, "password": PW})[1]["token"]


def ws_first_message(token, code):
    ws = websocket.create_connection("ws://127.0.0.1:5900/ws/tracking", timeout=5)
    ws.send(json.dumps({"type": "auth", "token": token, "code": code}))
    message = json.loads(ws.recv())
    ws.close()
    return message.get("type"), message.get("code") or message.get("status")


customer, staff = login("demo-customer@example.com"), login("demo-staff@example.com")
_, order = call("POST", PEDIDOS + "/pedidos?format=json", staff, {"items": [{"isbn": "9780000000006", "quantity": 1}]})
order = order["order"]
code = "LIB-MTY-%s-%06d" % (order["created_at"][:4], order["order_id"])
print("1. El personal crea un pedido (#%d) y todavía NO lo paga:" % order["order_id"])
print("   POST /tracking del dueño sin pago      ->", call("POST", GPS + "/tracking", staff, {"order_id": order["order_id"]})[1]["error"]["code"])
call("POST", PAGOS + "/pagos?format=json", staff, {"order_id": order["order_id"], "method": "efectivo", "amount": order["total"]},
     {"Idempotency-Key": str(uuid.uuid4())})
print("2. Ya pagado (código %s):" % code)
print("   dueño (personal) GET /tracking/<código> ->", call("GET", GPS + "/tracking/" + code, staff)[0])
status, body = call("GET", GPS + "/tracking/" + code, customer)
print("   OTRO cliente     GET /tracking/<código> ->", status, body["error"]["code"])
print("   sin token        GET /tracking/<código> ->", call("GET", GPS + "/tracking/" + code)[1]["error"]["code"])
print("   token falso      WebSocket              ->", ws_first_message("basura", code))
print("   OTRO cliente     WebSocket              ->", ws_first_message(customer, code))
print("   dueño (personal) WebSocket              ->", ws_first_message(staff, code))
print("   código con formato inválido (REST)      ->", call("GET", GPS + "/tracking/no-es-un-codigo", customer)[1]["error"]["code"])
