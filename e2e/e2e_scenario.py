#!/usr/bin/env python3
"""Escenario de punta a punta: los 6 servicios juntos, PostgreSQL real y Redis real.

Fase A  flujo normal: login -> JWT (20 min) -> books/authors/users/pedidos/pagos, caché e invalidaciones entre servicios,
        refresh con rotación, logout y REVOCACIÓN del JWT en TODOS los servicios.
Fase B  Redis CAÍDO: las lecturas cacheadas siguen por PostgreSQL; sesión, revocación, autorización y pagos fallan cerrado (503).
Fase C  Redis de vuelta: lo revocado sigue revocado (AOF), todo vuelve a funcionar y se limpia lo creado.
Uso: e2e_scenario.py {A|B|C}   (lo orquesta e2e/run_local.sh, que detiene/arranca Redis entre fases)
"""
import hashlib
import json
import os
import random
import sys
import uuid

import bcrypt
import jwt as pyjwt
import psycopg
import redis
import requests

PORTS = {"login": 5000, "books": 5001, "users": 5002, "authors": 5003, "pedidos": 5004, "pagos": 5005}
URL = {k: f"http://127.0.0.1:{v}" for k, v in PORTS.items()}
SECRET = os.environ["JWT_SECRET_KEY"]
ADMIN_DSN = os.environ["ADMIN_DSN"]
PASSWORD = "E2e-Clave-12345"
STATE = "/tmp/e2e_state.json"
FAILS = []


def step(title):
    print(f"\n● {title}")


def check(cond, message):
    print(("  ✔ " if cond else "  ✘ ") + message)
    if not cond:
        FAILS.append(message)
    return cond


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def j(response):
    try:
        return response.json()
    except ValueError:
        return {}


def err_code(response):
    e = j(response).get("error")
    return e.get("code") if isinstance(e, dict) else e


def r():
    return redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)


def db():
    return psycopg.connect(ADMIN_DSN, autocommit=True)


def make_user(role_id):
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(4)).decode()
    with db() as c:
        uid = c.execute("INSERT INTO users (email, password_hash, display_name, role_id) VALUES (%s, %s, 'E2E', %s) RETURNING user_id",
                        (email, pw_hash, role_id)).fetchone()[0]
    return {"user_id": uid, "email": email}


def login(user, session=None):
    s = session or requests.Session()
    resp = s.post(f"{URL['login']}/login?format=json", json={"email": user["email"], "password": PASSWORD}, timeout=10)
    return s, resp


def claims(token):
    return pyjwt.decode(token, SECRET, algorithms=["HS256"], options={"verify_exp": False, "verify_iss": False})


def load():
    with open(STATE) as f:
        return json.load(f)


def save(state):
    with open(STATE, "w") as f:
        json.dump(state, f)


# =============================================================================== FASE A
def phase_a():
    st = {}
    step("Los 6 servicios responden /health")
    for name in PORTS:
        check(requests.get(f"{URL[name]}/health?format=json", timeout=10).status_code == 200, f"{name} :{PORTS[name]} /health = 200")

    step("Usuarios de prueba: admin, staff y customer (rol en users.role_id)")
    admin, staff, cust = make_user(1), make_user(2), make_user(3)
    st["users"] = {"admin": admin, "staff": staff, "cust": cust}

    step("Login: JWT HS256 de 20 min con user_id, role_id y jti; refresh token; sesión y refresh en Redis")
    s_admin, resp = login(admin)
    body = j(resp)
    check(resp.status_code == 200 and body.get("token") and body.get("refresh_token"), "POST /login devuelve token y refresh_token")
    c = claims(body["token"])
    check(c["user_id"] == admin["user_id"] and c["role_id"] == 1 and c["exp"] - c["iat"] == 1200 and len(c["jti"]) >= 16,
          "claims: user_id, role_id=1, exp-iat=1200 s, jti")
    check(pyjwt.get_unverified_header(body["token"])["alg"] == "HS256", "algoritmo HS256")
    rd = r()
    check(len(list(rd.scan_iter("session:*"))) >= 1 and len(list(rd.scan_iter("refresh:*"))) >= 1, "Redis tiene session:* y refresh:*")
    key = next(rd.scan_iter("session:*"))
    check(1500 < rd.ttl(key) <= 1800, f"la sesión tiene TTL ~30 min ({rd.ttl(key)} s)")
    A = bearer(body["token"])
    s_staff, rs = login(staff)
    S = bearer(j(rs)["token"])

    step("books: lecturas públicas con caché Redis; escrituras con JWT y rol")
    check(requests.get(f"{URL['books']}/books?format=json", timeout=10).status_code == 200, "GET /books público = 200")
    check(rd.exists("books:list:all") == 1 and rd.ttl("books:list:all") <= 60, "books:list:all en Redis con TTL <= 60 s")
    isbn = "978" + "".join(random.choice("0123456789") for _ in range(10))
    st["isbn"] = isbn
    new_book = {"isbn": isbn, "title": f"Libro E2E {isbn[-4:]}", "publicationYear": 2024, "price": 150, "stock": 5,
                "category": "Tecnico", "format": "Rustica", "authors": "Autor E2E"}
    check(requests.post(f"{URL['books']}/books?format=json", json=new_book, timeout=10).status_code == 401, "POST /books sin token = 401")
    s_c, rc = login(cust)
    C = bearer(j(rc)["token"])
    check(requests.post(f"{URL['books']}/books?format=json", json=new_book, headers=C, timeout=10).status_code == 403, "POST /books como customer = 403")
    check(requests.post(f"{URL['books']}/books?format=json", json=new_book, headers=A, timeout=10).status_code == 201, "POST /books como admin = 201")
    check(rd.exists("books:list:all") == 0, "la escritura invalidó books:list:all")
    one = j(requests.get(f"{URL['books']}/books/{isbn}?format=json", timeout=10))
    check(one.get("stock") == 5 and one.get("authors") == "Autor E2E", "GET /books/<isbn> trae stock y autores reales")
    check(rd.exists(f"books:{isbn}") == 1, "books:<isbn> quedó en caché")

    step("authors: staff crea y vincula un autor; la caché del catálogo se invalida entre servicios")
    ra = requests.post(f"{URL['authors']}/authors?format=json", json={"first_name": "Ana E2E", "last_name": "Prueba"}, headers=S, timeout=10)
    check(ra.status_code == 201, "POST /authors como staff = 201")
    aid = j(ra)["author"]["author_id"]
    st["author_id"] = aid
    check(requests.post(f"{URL['authors']}/authors?format=json", json={"first_name": "X"}, headers=C, timeout=10).status_code == 403, "POST /authors como customer = 403")
    check(requests.post(f"{URL['authors']}/authors/{aid}/books?format=json", json={"isbn": isbn}, headers=S, timeout=10).status_code == 201, "vincular autor-libro = 201")
    check(rd.exists(f"books:{isbn}") == 0, "authors invalidó books:<isbn>")
    check("Ana E2E" in j(requests.get(f"{URL['books']}/books/{isbn}?format=json", timeout=10)).get("authors", ""), "/books ya muestra el autor nuevo")

    step("users: cada rol ve lo que le toca")
    check(requests.get(f"{URL['users']}/users/me?format=json", headers=C, timeout=10).status_code == 200, "customer GET /users/me = 200")
    check(requests.get(f"{URL['users']}/users?format=json", headers=C, timeout=10).status_code == 403, "customer GET /users = 403")
    check(requests.get(f"{URL['users']}/users?format=json", headers=A, timeout=10).status_code == 200, "admin GET /users = 200")
    check(requests.patch(f"{URL['users']}/users/{cust['user_id']}?format=json", json={"role_id": 1}, headers=C, timeout=10).status_code == 403,
          "customer no puede subirse el rol (403)")

    step("pedidos y pagos: stock transaccional, caché invalidada, idempotencia")
    ro = requests.post(f"{URL['pedidos']}/pedidos?format=json", json={"items": [{"isbn": isbn, "quantity": 2}]}, headers=C, timeout=10)
    check(ro.status_code == 201 and j(ro)["order"]["status"] == "pendiente", "customer crea pedido = 201 (pendiente)")
    order = j(ro)["order"]
    check(j(requests.get(f"{URL['books']}/books/{isbn}?format=json", timeout=10)).get("stock") == 3, "pedidos invalidó la caché: /books muestra stock 3")
    ro2 = requests.post(f"{URL['pedidos']}/pedidos?format=json", json={"items": [{"isbn": isbn, "quantity": 1}]}, headers=C, timeout=10)
    st["order2"] = j(ro2)["order"]["order_id"]
    idem = {**C, "Idempotency-Key": f"e2e-{uuid.uuid4().hex[:8]}"}
    pay = {"order_id": order["order_id"], "method": "tarjeta", "amount": order["total"]}
    rp = requests.post(f"{URL['pagos']}/pagos?format=json", json=pay, headers=idem, timeout=10)
    check(rp.status_code == 201 and j(rp)["payment"]["order_status"] == "pagado", "pago = 201 y el pedido queda «pagado»")
    rp2 = requests.post(f"{URL['pagos']}/pagos?format=json", json=pay, headers=idem, timeout=10)
    check(rp2.status_code == 200 and rp2.headers.get("Idempotent-Replay") == "true" and j(rp2)["payment"]["payment_id"] == j(rp)["payment"]["payment_id"],
          "reintento con la misma Idempotency-Key = 200 (mismo pago, sin cobrar otra vez)")
    check(requests.post(f"{URL['pagos']}/pagos?format=json", json=pay, headers=C, timeout=10).status_code == 400, "POST /pagos sin Idempotency-Key = 400")
    check(j(requests.get(f"{URL['pedidos']}/pedidos/{order['order_id']}?format=json", headers=C, timeout=10))["order"]["status"] == "pagado", "pedidos ve el estado «pagado»")
    check(requests.delete(f"{URL['pagos']}/pagos/1?format=json", headers=C, timeout=10).status_code == 405, "los pagos son inmutables (DELETE = 405)")

    step("Refresh con rotación y REVOCACIÓN del JWT anterior en todos los servicios")
    s_r, rl = login(cust)
    t1, r1 = j(rl)["token"], j(rl)["refresh_token"]
    rr = requests.post(f"{URL['login']}/token/refresh?format=json", json={"refresh_token": r1}, timeout=10)
    check(rr.status_code == 200, "POST /token/refresh = 200")
    t2, r2 = j(rr)["token"], j(rr)["refresh_token"]
    check(t2 != t1 and r2 != r1 and claims(t2)["jti"] != claims(t1)["jti"], "JWT y refresh nuevos (jti distinto)")
    for svc, path in (("pedidos", "/pedidos"), ("users", "/users/me")):
        old = requests.get(f"{URL[svc]}{path}?format=json", headers=bearer(t1), timeout=10)
        check(old.status_code == 401 and err_code(old) == "token_revoked", f"{svc}: el JWT anterior (jti revocado) = 401 token_revoked")
        check(requests.get(f"{URL[svc]}{path}?format=json", headers=bearer(t2), timeout=10).status_code == 200, f"{svc}: el JWT nuevo = 200")
    again = requests.post(f"{URL['login']}/token/refresh?format=json", json={"refresh_token": r1}, timeout=10)
    check(again.status_code == 401 and err_code(again) == "invalid_refresh_token", "el refresh token usado ya no sirve (un solo uso)")
    check(rd.exists(f"jwt:revoked:{claims(t1)['jti']}") == 1 and 0 < rd.ttl(f"jwt:revoked:{claims(t1)['jti']}") <= 1200, "Redis: jwt:revoked:<jti> con TTL <= 20 min")

    step("Logout: borra sesión y refresh, revoca el JWT en TODOS los servicios")
    rlo = s_r.post(f"{URL['login']}/logout?format=json", timeout=10)
    check(rlo.status_code == 200, "POST /logout = 200")
    for svc, path in (("pedidos", "/pedidos"), ("users", "/users/me"), ("pagos", "/pagos")):
        x = requests.get(f"{URL[svc]}{path}?format=json", headers=bearer(t2), timeout=10)
        check(x.status_code == 401 and err_code(x) == "token_revoked", f"{svc}: tras el logout el JWT = 401 token_revoked")
    check(requests.post(f"{URL['authors']}/authors?format=json", json={"first_name": "X"}, headers=bearer(t2), timeout=10).status_code == 401, "authors: escritura con JWT revocado = 401")
    x = requests.post(f"{URL['login']}/token/refresh?format=json", json={"refresh_token": r2}, timeout=10)
    check(x.status_code == 401, "el refresh token también murió con el logout")
    check(s_r.get(f"{URL['login']}/session?format=json", timeout=10).status_code == 401, "GET /session tras logout = 401")
    check(rd.exists(f"refresh:{hashlib.sha256(r2.encode()).hexdigest()}") == 0, "Redis: el refresh token fue borrado")

    step("Métricas")
    m = requests.get(f"{URL['users']}/metrics", headers=A, timeout=10)
    check(m.status_code == 200 and 'reason="token_revoked"' in m.text and 'service="users"' in m.text, "users /metrics (admin) cuenta los token_revoked")
    check(requests.get(f"{URL['users']}/metrics", headers=C, timeout=10).status_code == 403, "/metrics exige admin (customer = 403)")

    step("Tokens frescos para la fase B (Redis caído)")
    st["tokens"] = {"admin": j(login(admin)[1])["token"], "staff": j(login(staff)[1])["token"], "cust": j(login(cust)[1])["token"],
                    "revoked": t1}
    save(st)


# =============================================================================== FASE B
def phase_b():
    st = load()
    t, isbn = st["tokens"], st["isbn"]
    A, S, C = bearer(t["admin"]), bearer(t["staff"]), bearer(t["cust"])
    step("REDIS CAÍDO — lecturas cacheadas: siguen por PostgreSQL")
    check(requests.get(f"{URL['books']}/books?format=json", timeout=10).status_code == 200, "books GET /books = 200")
    check(requests.get(f"{URL['books']}/books/{isbn}?format=json", timeout=10).status_code == 200, "books GET /books/<isbn> = 200")
    check(requests.get(f"{URL['authors']}/authors?format=json", timeout=10).status_code == 200, "authors GET /authors (público) = 200")
    hb = requests.get(f"{URL['books']}/health?format=json", timeout=10)
    check(hb.status_code == 200 and j(hb).get("redis") == "unavailable", "books /health = 200 con redis «unavailable» (degradado)")

    step("REDIS CAÍDO — sesión, revocación y autorización fallan CERRADO (503, nada se modifica)")
    check(requests.post(f"{URL['books']}/books?format=json", json={"isbn": "1"}, headers=A, timeout=10).status_code == 503, "books POST con JWT válido = 503")
    for svc, method, path in (("users", "get", "/users/me"), ("pedidos", "get", "/pedidos"), ("pagos", "get", "/pagos"),
                              ("authors", "post", "/authors")):
        x = getattr(requests, method)(f"{URL[svc]}{path}?format=json", headers=S if svc == "authors" else C, json={"first_name": "X"} if method == "post" else None, timeout=10)
        check(x.status_code == 503 and err_code(x) == "redis_unavailable", f"{svc} {method.upper()} {path} = 503 redis_unavailable")
    lg = requests.post(f"{URL['login']}/login?format=json", json={"email": st["users"]["cust"]["email"], "password": PASSWORD}, timeout=10)
    check(lg.status_code == 503 and "token" not in j(lg), "login = 503 y NO entrega token")
    check(requests.get(f"{URL['login']}/health?format=json", timeout=10).status_code == 503, "login /health = 503")
    pay = requests.post(f"{URL['pagos']}/pagos?format=json", json={"order_id": st["order2"], "method": "tarjeta", "amount": 150},
                        headers={**C, "Idempotency-Key": "e2e-redis-down"}, timeout=10)
    check(pay.status_code == 503, "pagos POST = 503 (sin Redis no se cobra)")
    with db() as c:
        row = c.execute("SELECT s.name, (SELECT count(*) FROM payments p WHERE p.order_id = o.order_id) FROM orders o "
                        "JOIN order_statuses s USING (status_id) WHERE o.order_id = %s", (st["order2"],)).fetchone()
    check(row == ("pendiente", 0), "el pedido sigue «pendiente» y sin pagos")


# =============================================================================== FASE C
def phase_c():
    st = load()
    t, isbn = st["tokens"], st["isbn"]
    C = bearer(t["cust"])
    step("REDIS DE VUELTA — lo revocado sigue revocado y todo se recupera")
    x = requests.get(f"{URL['pedidos']}/pedidos?format=json", headers=bearer(t["revoked"]), timeout=10)
    check(x.status_code == 401 and err_code(x) == "token_revoked", "el JWT revocado antes de la caída sigue revocado (AOF)")
    check(requests.get(f"{URL['users']}/users/me?format=json", headers=C, timeout=10).status_code == 200, "un JWT vigente vuelve a funcionar")
    check(login(st["users"]["cust"])[1].status_code == 200, "login funciona otra vez")
    idem = {**C, "Idempotency-Key": "e2e-redis-up"}
    pay = requests.post(f"{URL['pagos']}/pagos?format=json", json={"order_id": st["order2"], "method": "efectivo", "amount": 150}, headers=idem, timeout=10)
    check(pay.status_code == 201, "el pago que dio 503 ahora sí se registra (201)")
    check(requests.get(f"{URL['books']}/health?format=json", timeout=10).json().get("redis") == "ok", "books /health vuelve a «redis: ok»")

    step("Limpieza de lo creado por la prueba")
    ids = [u["user_id"] for u in st["users"].values()]
    with db() as c:
        c.execute("DELETE FROM payments WHERE order_id IN (SELECT order_id FROM orders WHERE user_id = ANY(%s))", (ids,))
        c.execute("DELETE FROM orders WHERE user_id = ANY(%s)", (ids,))
        c.execute("DELETE FROM book_authors WHERE author_id = %s", (st["author_id"],))
        c.execute("DELETE FROM authors WHERE author_id = %s", (st["author_id"],))
        c.execute("DELETE FROM books WHERE isbn = %s", (isbn,))
        c.execute("DELETE FROM users WHERE user_id = ANY(%s)", (ids,))
    check(True, "datos de prueba eliminados")


if __name__ == "__main__":
    {"A": phase_a, "B": phase_b, "C": phase_c}[sys.argv[1]]()
    print(f"\n{'RESULTADO: TODO OK' if not FAILS else 'FALLARON ' + str(len(FAILS)) + ': ' + '; '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)
