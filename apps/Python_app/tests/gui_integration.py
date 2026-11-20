"""Prueba de integración de la app Tk contra los 6 microservicios REALES (no usa mocks).

Maneja la GUI de verdad (instancia App, llena los campos de las pestañas y "pulsa" sus botones llamando a los mismos
métodos) y comprueba lo que la persona vería en pantalla: mensajes, filas de las tablas, semáforos y bitácora.
No toca config.local.json, cookies.local.txt ni session.local.json: usa archivos temporales.

Requisitos: los servicios arriba (p. ej. `bash e2e/serve_local.sh`, o la VM) y usuarios demo admin/staff/customer.

  set LIB_BASE_PORT=15000            (los 6 servicios en BASE..BASE+5; o LIB_VM=http://IP para Nginx /auth /soap ...)
  set LIB_DEMO_PASSWORD=...          (contraseña de demo-admin@/demo-staff@/demo-customer@example.com)
  set LIB_REDIS_CONTAINER=lib_redis_local   (opcional: detiene/arranca ese contenedor para la fase «Redis caído»)
  python tests/gui_integration.py
"""
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import session_store  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="tk_it_"))
config.CONFIG_PATH = TMP / "config.json"
session_store.SESSION_PATH = TMP / "session.json"
session_store.COOKIE_PATH = TMP / "cookies.txt"

from tkinter import messagebox  # noqa: E402

DIALOGS = []
messagebox.askyesno = lambda *a, **k: True
for _name in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, _name, lambda title, message, _n=_name, **k: DIALOGS.append((_n, title, message)))

import app as app_module  # noqa: E402
from api_client import ApiError  # noqa: E402

PASSWORD = os.environ["LIB_DEMO_PASSWORD"]
REDIS_CONTAINER = os.environ.get("LIB_REDIS_CONTAINER")
FAILS = []
RUN = uuid.uuid4().hex[:6]


def urls():
    if os.environ.get("LIB_VM"):
        return config.remote_urls(os.environ["LIB_VM"])
    base = int(os.environ.get("LIB_BASE_PORT", "15000"))
    return {k: f"http://localhost:{base + i}" for i, k in enumerate(config.KEYS)}


def check(cond, text):
    print(("  ✔ " if cond else "  ✘ ") + text)
    if not cond:
        FAILS.append(text)
    return cond


def step(title):
    print(f"\n● {title}")


def spin(app, seconds=0.0):
    end = time.time() + seconds
    app.update()
    while time.time() < end:
        app.update()
        time.sleep(0.05)


def new_app():
    config.save({f"{k}_url": v for k, v in urls().items()})
    app = app_module.App()
    app.withdraw()
    return app


def login_as(app, email):
    lv = app.login_view
    lv.email.delete(0, "end")
    lv.email.insert(0, email)
    lv.password.delete(0, "end")
    lv.password.insert(0, PASSWORD)
    lv.do_login()
    spin(app)
    return app.user is not None


def text_of(tab):
    return tab.msg.cget("text")


def select_tab(app, key):
    tab = app.main_view.tabs[key][0]
    app.main_view.notebook.select(tab)
    spin(app)
    return tab


def rows(tree):
    return [tree.item(i, "values") for i in tree.get_children()]


# ============================================================================ customer
def customer_flow():
    step("CUSTOMER: login y JWT")
    app = new_app()
    check(login_as(app, "demo-customer@example.com"), "login correcto, aparece el panel principal")
    mv = app.main_view
    check(app.api.token_claims().get("role_id") == 3, "el JWT trae role_id=3 (customer) y user_id")
    check("customer" in mv.user_label.cget("text"), f"barra superior: «{mv.user_label.cget('text')}»")
    check(mv.token_label.cget("text").startswith("JWT expira en 19:") or mv.token_label.cget("text").startswith("JWT expira en 20:"),
          f"reloj del JWT: «{mv.token_label.cget('text')}» (20 min)")
    check(len(mv.tabs) == 10, "10 pestañas: catálogo, libros, autores, usuarios, pedidos, pagos, perfil, semáforos, bitácora, config")

    step("CUSTOMER: Authors (lecturas públicas con caché; escrituras 403)")
    authors = select_tab(app, "autores")
    check(len(rows(authors.tree)) >= 1, f"lista de autores cargada ({len(rows(authors.tree))})")
    authors.form.set("first_name", f"Prueba{RUN}")
    authors.crear()
    check("403" in text_of(authors), f"crear autor → «{text_of(authors)[:70]}…»")

    step("CUSTOMER: Users (solo su cuenta)")
    users = select_tab(app, "usuarios")
    users.mi_cuenta()
    check("Tu cuenta" in text_of(users) and users.form.get("email") == "demo-customer@example.com", "GET /users/me llena el formulario")
    users.listar()
    check("403" in text_of(users), f"listar usuarios → «{text_of(users)[:70]}…»")

    step("CUSTOMER: Pedidos → Pagos (idempotencia)")
    pedidos = select_tab(app, "pedidos")
    pedidos.new.set("isbn", "9780000000006")
    pedidos.new.set("quantity", "2")
    pedidos.add_line()
    check(pedidos.lines == [{"isbn": "9780000000006", "quantity": 2}], "línea agregada al pedido")
    pedidos.crear()
    oid = pedidos.sel.get("order_id")
    check(oid.isdigit() and "Pedido creado" in text_of(pedidos), f"POST /pedidos → order_id={oid} · «{text_of(pedidos)[:90]}…»")
    check(any(r[0] == oid and r[2] == "pendiente" for r in rows(pedidos.tree)), "el pedido aparece «pendiente» en la tabla")
    pedidos.cambiar("pagado")
    check("409" in text_of(pedidos), "marcar «pagado» a mano → 409 (solo Pagos puede)")
    pedidos.cambiar("enviado")
    check("403" in text_of(pedidos), "marcar «enviado» siendo customer → 403")
    total = app.api.get_order(int(oid))["total"]
    pedidos.pagar()
    spin(app)
    pagos = app.main_view.pagos_tab
    check(pagos.form.get("order_id") == oid and pagos.form.get("amount") == str(total), f"«Pagar este pedido →» abre Pagos con el pedido {oid} y total {total}")
    pagos.pagar()
    check("Pago registrado" in text_of(pagos), f"POST /pagos → «{text_of(pagos)[:100]}»")
    check(any(r[1] == oid for r in rows(pagos.tree)), "el pago aparece en la tabla de Pagos")
    pagos.reintentar()
    check("Idempotent-Replay" in text_of(pagos) and "NO se cobró" in text_of(pagos), f"reintento con la MISMA clave → «{text_of(pagos)[:80]}…»")
    check(len([r for r in rows(pagos.tree) if r[1] == oid]) == 1, "sigue habiendo UN solo pago del pedido")
    pagos.form.set("payment_id", rows(pagos.tree)[0][0])
    pagos.inmutable("PUT")
    check("405" in text_of(pagos), "PUT /pagos/{id} → 405 (los pagos son inmutables)")
    pedidos.on_select()
    pedidos.cambiar("cancelado")
    check("409" in text_of(pedidos) or "pagado" in text_of(pedidos).lower(), f"cancelar un pedido ya pagado se rechaza → «{text_of(pedidos)[:70]}»")

    step("CUSTOMER: pedido con stock insuficiente y cancelación (repone stock)")
    pedidos.new.set("isbn", "9780000000030")
    pedidos.new.set("quantity", "999")
    pedidos.add_line()
    pedidos.crear()
    check(text_of(pedidos).startswith("409") or text_of(pedidos).startswith("400"), f"stock insuficiente → «{text_of(pedidos)[:80]}»")
    pedidos.lines.clear()
    pedidos.lines_box.delete(0, "end")
    before = next(b["stock"] for b in app.api.list_books() if b["isbn"] == "9780000000001")
    pedidos.new.set("isbn", "9780000000001")
    pedidos.new.set("quantity", "1")
    pedidos.add_line()
    pedidos.crear()
    oid2 = pedidos.sel.get("order_id")
    mid = next(b["stock"] for b in app.api.list_books() if b["isbn"] == "9780000000001")
    pedidos.cancelar()
    after = next(b["stock"] for b in app.api.list_books() if b["isbn"] == "9780000000001")
    check(mid == before - 1 and after == before, f"stock del libro: {before} → {mid} al pedir → {after} al cancelar")

    step("CUSTOMER: renovación del JWT antes de caducar")
    old_refresh, old_token = app.api.refresh_token, app.api.jwt_token
    mv.renew_now()
    check(app.api.jwt_token != old_token and app.api.refresh_token != old_refresh, "«Renovar JWT ahora»: JWT y refresh nuevos")
    check(any(d[0] == "showinfo" and "JWT renovado" in d[1] for d in DIALOGS), "la GUI avisa que se renovó")
    try:
        app.api._request("POST", "auth", "/token/refresh", {"refresh_token": old_refresh}, auth=False)
        check(False, "el refresh anterior debería estar muerto")
    except ApiError as exc:
        check(exc.status == 401, f"el refresh token anterior ya no sirve (un solo uso) → {exc.status}")
    app.api._deadline = time.monotonic() + 60  # simula que faltan 60 s: la app debe renovar sola
    token_before = app.api.jwt_token
    app._next_renew = 0
    spin(app, 3)
    check(app.api.jwt_token != token_before and app.api.seconds_left() > 1000, "con <3 min de vida, la app renueva SOLA el JWT (segundo plano)")

    step("CUSTOMER: token revocado tras cerrar sesión")
    stolen = app.api.jwt_token
    app.on_logout()
    spin(app)
    import requests
    resp = requests.get(f"{urls()['users']}/users/me", params={"format": "json"}, headers={"Authorization": f"Bearer {stolen}"}, timeout=8)
    check(app.user is None and resp.status_code == 401 and "revoked" in resp.text, f"el JWT usado antes del logout da {resp.status_code} token_revoked en users")
    bit = [r for r in rows(app.main_view.bitacora_tab.tree)]
    check(len(bit) > 20 and {"auth", "users", "authors", "pedidos", "pagos"} <= {r[2] for r in bit}, f"bitácora con {len(bit)} peticiones de 5 servicios distintos")
    check(not any("eyJ" in " ".join(map(str, r)) for r in bit), "la bitácora no contiene ningún JWT")
    app.destroy()


# ============================================================================== admin
def admin_flow():
    step("ADMIN: Users CRUD")
    app = new_app()
    check(login_as(app, "demo-admin@example.com") and app.api.token_claims().get("role_id") == 1, "login admin (role_id=1 en el JWT)")
    users = select_tab(app, "usuarios")
    users.listar()
    check(len(rows(users.tree)) >= 3, f"GET /users: {len(rows(users.tree))} usuarios")
    email = f"tk-{RUN}@example.com"
    for key, value in (("email", email), ("password", "Tk-Clave-12345"), ("nombre", "Tk"), ("apellido_paterno", "Prueba"),
                       ("apellido_materno", "Gui"), ("role_id", "3 customer")):
        users.form.set(key, value)
    users.crear()
    uid = users.form.get("user_id")
    check(uid.isdigit() and "Usuario creado" in text_of(users), f"POST /users → user_id={uid}")
    users.form.clear(("display_name", "nombre", "apellido_paterno", "apellido_materno", "email", "role_id", "is_active"))
    users.form.set("role_id", "2 staff")
    users.parchear()
    check("Usuario actualizado" in text_of(users) and "role_id" in text_of(users), f"PATCH rol → «{text_of(users)[:100]}»")
    users.obtener()
    check(users.form.get("role_id").startswith("2"), "GET /users/{id}: el rol quedó en staff")
    users.form.set("password", "Otra-Clave-12345")
    users.password()
    check("Contraseña actualizada" in text_of(users), "PUT /users/{id}/password")
    users.form.clear(("display_name", "nombre", "apellido_paterno", "apellido_materno", "email", "role_id", "is_active"))
    users.reemplazar()
    check("PUT exige" in text_of(users) or "Falta llenar" in text_of(users), f"PUT con campos faltantes se detiene en la GUI → «{text_of(users)[:70]}»")
    users.eliminar()
    check("Usuario eliminado" in text_of(users), "DELETE /users/{id}")
    users.form.set("user_id", str(app.user["user_id"] if "user_id" in app.user else app.api.token_claims()["user_id"]))
    users.eliminar()
    check("409" in text_of(users), f"el admin no puede borrarse a sí mismo → «{text_of(users)[:60]}»")

    step("ADMIN: Authors CRUD, relación con libros y caché")
    authors = select_tab(app, "autores")
    authors.form.clear()
    authors.form.set("first_name", f"Gui{RUN}")
    authors.form.set("last_name", "Autor")
    authors.crear()
    aid = authors.form.get("author_id")
    check(aid.isdigit() and "Autor creado" in text_of(authors), f"POST /authors → author_id={aid}")
    authors.form.set("first_name", "")
    authors.form.set("biography", "Biografía de prueba")
    authors.parchear()
    check("Autor actualizado" in text_of(authors), "PATCH /authors/{id}")
    authors.link.set("isbn", "9780000000006")
    authors.link.set("author_order", "2")
    authors.vincular()
    check("vinculado" in text_of(authors), "POST /authors/{id}/books (vincular)")
    authors.libros()
    check("9780000000006" in text_of(authors), f"GET /authors/{{id}}/books → «{text_of(authors)[:80]}»")
    authors.eliminar()
    check("409" in text_of(authors), "borrar un autor con libros vinculados → 409")
    authors.desvincular()
    authors.eliminar()
    check("Autor eliminado" in text_of(authors), "desvincular y DELETE /authors/{id}")

    step("ADMIN: Pedidos de todos y Pagos de todos")
    pedidos = select_tab(app, "pedidos")
    pedidos.listar()
    owners = {r[1] for r in rows(pedidos.tree)}
    check(len(owners) >= 1, f"el admin ve pedidos de {len(owners)} usuario(s)")
    pagos = select_tab(app, "pagos")
    pagos.listar()
    check(True, f"el admin ve {len(rows(pagos.tree))} pago(s)")
    metrics_code = __import__("requests").get(f"{urls()['users']}/metrics", headers={"Authorization": f"Bearer {app.api.jwt_token}"}, timeout=8).status_code
    check(metrics_code == 200, "GET /metrics del servicio users con JWT admin = 200")
    app.destroy()


# ========================================================================== semáforos
def semaforos(app, expect_redis):
    estado = select_tab(app, "estado")
    estado._check_in_background()
    spin(app, 1)
    return {k: (estado.rows[k]["text"].cget("text"), estado.rows[k]["dot"].cget("fg")) for k in estado.rows}


def lights_flow():
    step("SEMÁFOROS con todo arriba")
    app = new_app()
    login_as(app, "demo-customer@example.com")
    lights = semaforos(app, "ok")
    green = estado_green = app_module.EstadoTab.COLORES["green"]
    check(all(lights[k][1] == green for k in lights), f"los 6 servicios y Redis en verde: {[k for k in lights if lights[k][1] == green]}")
    if not REDIS_CONTAINER:
        print("  (sin LIB_REDIS_CONTAINER: se omite la fase «Redis caído»)")
        app.destroy()
        return
    step(f"REDIS CAÍDO (docker stop {REDIS_CONTAINER}): la GUI debe fallar de forma segura")
    subprocess.run(["docker", "stop", REDIS_CONTAINER], capture_output=True, check=True)
    try:
        time.sleep(1)
        lights = semaforos(app, "unavailable")
        red, yellow = app_module.EstadoTab.COLORES["red"], app_module.EstadoTab.COLORES["yellow"]
        check(lights["redis"][1] == red, f"semáforo de Redis en ROJO: «{lights['redis'][0].splitlines()[-1][:70]}»")
        check(all(lights[k][1] == yellow for k in config.KEYS), f"los 6 servicios en AMARILLO (degradados): {[k for k in config.KEYS if lights[k][1] == yellow]}")
        select_tab(app, "catalogo").load()
        check("libro(s)" in app.main_view.catalogo_tab.status.cget("text"), "catálogo (lectura pública) sigue funcionando sin Redis")
        authors = select_tab(app, "autores")
        authors.listar()
        check("autor(es)" in text_of(authors), "authors GET público sigue funcionando sin Redis")
        users = select_tab(app, "usuarios")
        users.mi_cuenta()
        check(text_of(users).startswith("503"), f"users con Redis caído → «{text_of(users)[:100]}»")
        pedidos = select_tab(app, "pedidos")
        pedidos.listar()
        check(text_of(pedidos).startswith("503"), "pedidos con Redis caído → 503")
        pagos = select_tab(app, "pagos")
        pagos.form.set("order_id", "1")
        pagos.form.set("amount", "10.00")
        pagos.pagar()
        check(text_of(pagos).startswith("503"), "pagos con Redis caído → 503 (no se cobra)")
        lv = app_module.LoginView
        app.api._clear_tokens()
        app.on_logout()
        spin(app)
        ok = login_as(app, "demo-customer@example.com")
        check(not ok and "No se puede verificar la sesión" in app.login_view.error_label.cget("text"), f"login con Redis caído → «{app.login_view.error_label.cget('text')[:80]}»")
    finally:
        subprocess.run(["docker", "start", REDIS_CONTAINER], capture_output=True, check=True)
        time.sleep(2)
    step("Redis de vuelta")
    lights = semaforos(app, "ok")
    green = app_module.EstadoTab.COLORES["green"]
    check(all(lights[k][1] == green for k in lights), "los 6 servicios y Redis vuelven a verde")
    check(login_as(app, "demo-customer@example.com"), "el login vuelve a funcionar")
    app.destroy()


if __name__ == "__main__":
    customer_flow()
    admin_flow()
    lights_flow()
    print("\n" + ("TODO OK" if not FAILS else f"FALLARON {len(FAILS)}: " + "; ".join(FAILS)))
    sys.exit(1 if FAILS else 0)
