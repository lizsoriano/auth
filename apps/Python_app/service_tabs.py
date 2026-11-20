"""Pestañas CRUD de los microservicios Users, Authors, Pedidos y Pagos, y la bitácora de peticiones.

Cada pestaña habla con SU microservicio (otro puerto, otra URL) solo a través de api_client.ApiClient.
Los errores de seguridad se muestran tal cual los devuelve el servidor, con su código HTTP:
  401 -> falta el JWT o es inválido/revocado/vencido (si no se pudo renovar, se vuelve al login)
  403 -> el JWT es válido pero el rol no alcanza para esa operación
  503 -> Redis (o PostgreSQL) no responde: el servicio falla cerrado y NO modifica nada
"""
import csv
import tkinter as tk
import uuid
from tkinter import filedialog, messagebox, ttk

from api_client import ApiError

OK, WARN, BAD, MUTED = "#0a7a2a", "#b36b00", "#b00020", "#666666"
ROLE_CHOICES = ["", "1 admin", "2 staff", "3 customer"]
STATUS_CHOICES = ["", "pendiente", "pagado", "enviado", "cancelado"]
METHOD_CHOICES = ["tarjeta", "transferencia", "efectivo"]
FAILED = object()  # lo que devuelve CrudTab.run() cuando el servidor respondió con error


def _first_int(text):
    """'2 staff' -> 2 ; '' -> None."""
    text = str(text).strip()
    return int(text.split()[0]) if text else None


def _int_or_none(text):
    text = str(text).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"«{text}» no es un número entero")


# ======================================================================
# Formulario genérico
# ======================================================================
class Form(ttk.LabelFrame):
    """Campos etiquetados. spec = [(clave, etiqueta, tipo)] con tipo 'entry' | 'password' | lista de opciones (combobox)."""

    def __init__(self, parent, title, spec, width=26):
        super().__init__(parent, text=title, padding=8)
        self.widgets = {}
        for row, (key, label, kind) in enumerate(spec):
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", pady=2)
            if isinstance(kind, (list, tuple)):
                widget = ttk.Combobox(self, values=list(kind), width=width - 3, state="readonly")
                widget.set(kind[0])
            else:
                widget = ttk.Entry(self, width=width, show="•" if kind == "password" else "")
            widget.grid(row=row, column=1, sticky="w", padx=6, pady=2)
            self.widgets[key] = widget

    def get(self, key):
        return self.widgets[key].get().strip()

    def set(self, key, value):
        widget = self.widgets[key]
        text = "" if value is None else str(value)
        if isinstance(widget, ttk.Combobox):
            widget.set(text if text in widget.cget("values") else (widget.cget("values")[0] if not text else text))
        else:
            widget.delete(0, "end")
            widget.insert(0, text)

    def clear(self, keys=None):
        for key in keys or self.widgets:
            widget = self.widgets[key]
            if isinstance(widget, ttk.Combobox):
                widget.set(widget.cget("values")[0])
            else:
                widget.delete(0, "end")


# ======================================================================
# Base de las pestañas
# ======================================================================
class CrudTab(ttk.Frame):
    def __init__(self, parent, app, hint):
        super().__init__(parent, padding=8)
        self.app = app
        ttk.Label(self, text=hint, foreground=MUTED, wraplength=1000, justify="left").pack(anchor="w")
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, pady=6)
        self.msg = ttk.Label(self, text="", wraplength=1000, justify="left")
        self.msg.pack(fill="x")

    # ---- mensajes
    def ok(self, text):
        entry = self.app.last_request
        trace = f"[{entry['method']} {entry['service']}{entry['path']} → {entry['status']} · {entry['ms']} ms]  " if entry else ""
        self.msg.config(text=f"{trace}{text}", foreground=OK)

    def info(self, text):
        self.msg.config(text=text, foreground=MUTED)

    def fail(self, exc):
        """Muestra el error con su código HTTP y, si el JWT ya no es renovable, regresa al login."""
        if exc.status == 401 and not self.app.api.jwt_token:
            messagebox.showwarning("Sesión vencida", f"{exc.message}\n\nInicia sesión de nuevo.")
            self.app.on_logout()
            return
        color = WARN if exc.status in (403, 409, 405) else BAD
        titulo = {401: "401 No autenticado", 403: "403 Sin permiso para tu rol", 405: "405 Método no permitido",
                  409: "409 Conflicto", 503: "503 Servicio no disponible (falla cerrado, no se modificó nada)",
                  400: "400 Datos inválidos", 404: "404 No encontrado"}.get(exc.status, f"HTTP {exc.status}" if exc.status else "Sin conexión")
        self.msg.config(text=f"{titulo}: {exc.message}", foreground=color)

    def run(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiError as exc:
            self.fail(exc)
            return FAILED
        except ValueError as exc:
            self.msg.config(text=str(exc), foreground=BAD)
            return FAILED

    def need(self, form, *keys):
        """True si todos los campos están llenos; si no, avisa cuáles faltan."""
        missing = [k for k in keys if not form.get(k)]
        if missing:
            self.msg.config(text=f"Falta llenar: {', '.join(missing)}", foreground=BAD)
        return not missing

    # ---- árbol
    def make_tree(self, parent, columns, widths, height=14):
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="browse", height=height)
        for col, width in zip(columns, widths):
            tree.heading(col, text=col)
            tree.column(col, width=width, anchor="w")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=1, column=0, sticky="nsew")
        scroll.grid(row=1, column=1, sticky="ns")
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        return tree

    def fill_tree(self, tree, rows, iid_key, columns):
        tree.delete(*tree.get_children())
        for row in rows:
            tree.insert("", "end", iid=str(row[iid_key]), values=[row.get(c, "") if row.get(c) is not None else "" for c in columns])

    def buttons(self, parent, specs, columns=3):
        frame = ttk.Frame(parent)
        for i, (text, command) in enumerate(specs):
            ttk.Button(frame, text=text, command=command).grid(row=i // columns, column=i % columns, sticky="ew", padx=2, pady=2)
        return frame

    def on_shown(self):
        """Se llama al abrir la pestaña: carga la lista si todavía no se cargó."""


# ======================================================================
# USERS
# ======================================================================
class UsersTab(CrudTab):
    COLUMNS = ("user_id", "email", "display_name", "role_name", "is_active")

    def __init__(self, parent, app):
        super().__init__(parent, app, "Microservicio USERS (puerto 5002, /users). Solo admin lista, crea, cambia rol y borra. "
                                      "staff y customer solo ven y modifican SU cuenta (lo demás responde 403).")
        left, right = ttk.Frame(self.body), ttk.Frame(self.body)
        left.pack(side="left", fill="both", expand=True)
        right.pack(side="left", fill="y", padx=(10, 0))
        bar = ttk.Frame(left)
        bar.grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Button(bar, text="↻ Listar (GET /users)", command=self.listar).pack(side="left", padx=2)
        ttk.Button(bar, text="Mi cuenta (GET /users/me)", command=self.mi_cuenta).pack(side="left", padx=2)
        self.tree = self.make_tree(left, self.COLUMNS, (60, 200, 150, 80, 70))
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        self.form = Form(right, "Usuario", [
            ("user_id", "user_id", "entry"), ("email", "Email", "entry"), ("display_name", "Nombre a mostrar", "entry"),
            ("nombre", "Nombre", "entry"), ("apellido_paterno", "Apellido paterno", "entry"),
            ("apellido_materno", "Apellido materno", "entry"), ("password", "Password (nueva)", "password"),
            ("current_password", "Password actual", "password"), ("role_id", "Rol", ROLE_CHOICES),
            ("is_active", "Activo", ["", "true", "false"])])
        self.form.pack(fill="x")
        self.buttons(right, [
            ("Obtener (GET)", self.obtener), ("Crear (POST)", self.crear), ("Reemplazar (PUT)", self.reemplazar),
            ("Modificar (PATCH)", self.parchear), ("Cambiar password (PUT)", self.password),
            ("Eliminar (DELETE)", self.eliminar), ("Limpiar", self.form.clear)], columns=2).pack(fill="x", pady=6)

    def on_shown(self):
        pass

    def _fill(self, user):
        for key in ("user_id", "email", "display_name", "nombre", "apellido_paterno", "apellido_materno"):
            self.form.set(key, user.get(key))
        self.form.set("role_id", f"{user.get('role_id')} {user.get('role_name')}")
        self.form.set("is_active", str(bool(user.get("is_active"))).lower())

    def on_select(self, _event=None):
        selection = self.tree.selection()
        if selection:
            self.form.set("user_id", selection[0])

    def _uid(self):
        return _int_or_none(self.form.get("user_id"))

    def listar(self, quiet=False):
        users = self.run(self.app.api.list_users)
        if users is FAILED:
            return
        self.fill_tree(self.tree, users, "user_id", self.COLUMNS)
        if not quiet:
            self.ok(f"{len(users)} usuario(s).")

    def mi_cuenta(self):
        user = self.run(self.app.api.my_user)
        if user is not FAILED:
            self._fill(user)
            self.ok("Tu cuenta (según el user_id del JWT).")

    def obtener(self):
        uid = self.run(self._uid)
        if uid in (FAILED, None):
            return self.info("Escribe el user_id.") if uid is None else None
        user = self.run(self.app.api.get_user, uid)
        if user is not FAILED:
            self._fill(user)
            self.ok(f"Usuario {uid} cargado.")

    def crear(self):
        f = self.form
        if not self.need(f, "email", "password", "nombre", "apellido_paterno", "apellido_materno"):
            return
        body = {k: f.get(k) for k in ("email", "password", "nombre", "apellido_paterno", "apellido_materno")}
        if f.get("display_name"):
            body["display_name"] = f.get("display_name")
        if f.get("role_id"):
            body["role_id"] = _first_int(f.get("role_id"))
        data = self.run(self.app.api.create_user, **body)
        if data is not FAILED:
            f.clear(("password", "current_password"))
            self.ok(f"{data.get('message')} user_id={data['user']['user_id']}")
            self._fill(data["user"])
            self.listar(quiet=True)

    def reemplazar(self):
        f = self.form
        uid = self.run(self._uid)
        if uid in (FAILED, None) or not self.need(f, "email", "display_name", "nombre", "apellido_paterno",
                                                  "apellido_materno", "role_id", "is_active"):
            return self.info("PUT exige TODOS los campos y el user_id (para cambios parciales usa PATCH).") if uid in (None,) else None
        data = self.run(self.app.api.replace_user, uid, email=f.get("email"), display_name=f.get("display_name"),
                        nombre=f.get("nombre"), apellido_paterno=f.get("apellido_paterno"),
                        apellido_materno=f.get("apellido_materno"), role_id=_first_int(f.get("role_id")),
                        is_active=f.get("is_active") == "true")
        if data is not FAILED:
            self.ok(data.get("message", "Reemplazado."))
            self.listar(quiet=True)

    def parchear(self):
        f = self.form
        uid = self.run(self._uid)
        if uid in (FAILED, None):
            return self.info("Escribe el user_id.") if uid is None else None
        body = {k: f.get(k) for k in ("email", "display_name", "nombre", "apellido_paterno", "apellido_materno") if f.get(k)}
        if f.get("role_id"):
            body["role_id"] = _first_int(f.get("role_id"))
        if f.get("is_active"):
            body["is_active"] = f.get("is_active") == "true"
        if not body:
            return self.msg.config(text="Llena al menos un campo para el PATCH.", foreground=BAD)
        data = self.run(self.app.api.patch_user, uid, **body)
        if data is not FAILED:
            self.ok(f"{data.get('message')} (solo se enviaron: {', '.join(body)})")
            self.listar(quiet=True)

    def password(self):
        f = self.form
        uid = self.run(self._uid)
        if uid in (FAILED, None) or not self.need(f, "password"):
            return self.info("Escribe el user_id.") if uid is None else None
        data = self.run(self.app.api.set_user_password, uid, f.get("password"), f.get("current_password") or None)
        if data is not FAILED:
            f.clear(("password", "current_password"))
            self.ok(data.get("message", "Contraseña actualizada."))

    def eliminar(self):
        uid = self.run(self._uid)
        if uid in (FAILED, None):
            return self.info("Escribe el user_id.") if uid is None else None
        if not messagebox.askyesno("Confirmar eliminación", f"¿Eliminar al usuario {uid}? No se puede deshacer."):
            return
        data = self.run(self.app.api.delete_user, uid)
        if data is not FAILED:
            self.ok(data.get("message", "Eliminado."))
            self.listar(quiet=True)


# ======================================================================
# AUTHORS
# ======================================================================
class AuthorsTab(CrudTab):
    COLUMNS = ("author_id", "first_name", "last_name", "books_count")

    def __init__(self, parent, app):
        super().__init__(parent, app, "Microservicio AUTHORS (puerto 5003, /authors). Las lecturas son públicas y salen de la caché "
                                      "de Redis (TTL corto); crear/modificar/borrar/vincular exige JWT con rol admin o staff.")
        left, right = ttk.Frame(self.body), ttk.Frame(self.body)
        left.pack(side="left", fill="both", expand=True)
        right.pack(side="left", fill="y", padx=(10, 0))
        bar = ttk.Frame(left)
        bar.grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Button(bar, text="↻ Listar (GET /authors)", command=self.listar).pack(side="left", padx=2)
        self.tree = self.make_tree(left, self.COLUMNS, (70, 170, 170, 90))
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        self.form = Form(right, "Autor", [("author_id", "author_id", "entry"), ("first_name", "Nombre", "entry"),
                                          ("last_name", "Apellido", "entry"), ("biography", "Biografía", "entry")])
        self.form.pack(fill="x")
        self.link = Form(right, "Relación con libros", [("isbn", "ISBN del libro", "entry"), ("author_order", "Orden (1-99)", "entry")])
        self.link.pack(fill="x", pady=(8, 0))
        self.buttons(right, [
            ("Obtener (GET)", self.obtener), ("Crear (POST)", self.crear), ("Reemplazar (PUT)", self.reemplazar),
            ("Modificar (PATCH)", self.parchear), ("Eliminar (DELETE)", self.eliminar), ("Limpiar", self.form.clear),
            ("Libros del autor (GET)", self.libros), ("Vincular libro (POST)", self.vincular),
            ("Desvincular (DELETE)", self.desvincular)], columns=3).pack(fill="x", pady=6)
        self._loaded = False

    def on_shown(self):
        if not self._loaded:
            self._loaded = True
            self.listar(quiet=True)

    def on_select(self, _event=None):
        selection = self.tree.selection()
        if selection:
            self.form.set("author_id", selection[0])
            values = self.tree.item(selection[0], "values")
            self.form.set("first_name", values[1])
            self.form.set("last_name", values[2])

    def _aid(self):
        return _int_or_none(self.form.get("author_id"))

    def _need_id(self):
        aid = self.run(self._aid)
        if aid is None:
            self.msg.config(text="Escribe el author_id (o elige una fila).", foreground=BAD)
        return None if aid in (None, FAILED) else aid

    def listar(self, quiet=False):
        authors = self.run(self.app.api.list_authors)
        if authors is FAILED:
            return
        self.fill_tree(self.tree, authors, "author_id", self.COLUMNS)
        if not quiet:
            self.ok(f"{len(authors)} autor(es).")

    def obtener(self):
        aid = self._need_id()
        if aid is None:
            return
        author = self.run(self.app.api.get_author, aid)
        if author is not FAILED:
            for key in ("first_name", "last_name", "biography"):
                self.form.set(key, author.get(key))
            self.ok(f"Autor {aid} cargado.")

    def crear(self):
        f = self.form
        if not self.need(f, "first_name"):
            return
        data = self.run(self.app.api.create_author, first_name=f.get("first_name"), last_name=f.get("last_name"),
                        biography=f.get("biography"))
        if data is not FAILED:
            self.form.set("author_id", data["author"]["author_id"])
            self.ok(f"{data.get('message')} author_id={data['author']['author_id']}")
            self.listar(quiet=True)

    def reemplazar(self):
        aid = self._need_id()
        if aid is None or not self.need(self.form, "first_name"):
            return
        f = self.form
        data = self.run(self.app.api.replace_author, aid, first_name=f.get("first_name"), last_name=f.get("last_name"),
                        biography=f.get("biography"))
        if data is not FAILED:
            self.ok(data.get("message", "Reemplazado."))
            self.listar(quiet=True)

    def parchear(self):
        aid = self._need_id()
        if aid is None:
            return
        f = self.form
        body = {k: f.get(k) for k in ("first_name", "last_name", "biography") if f.get(k)}
        if not body:
            return self.msg.config(text="Llena al menos un campo para el PATCH.", foreground=BAD)
        data = self.run(self.app.api.patch_author, aid, **body)
        if data is not FAILED:
            self.ok(f"{data.get('message')} (solo se enviaron: {', '.join(body)})")
            self.listar(quiet=True)

    def eliminar(self):
        aid = self._need_id()
        if aid is None or not messagebox.askyesno("Confirmar eliminación", f"¿Eliminar al autor {aid}?"):
            return
        data = self.run(self.app.api.delete_author, aid)
        if data is not FAILED:
            self.ok(data.get("message", "Eliminado."))
            self.listar(quiet=True)

    def libros(self):
        aid = self._need_id()
        if aid is None:
            return
        books = self.run(self.app.api.author_books, aid)
        if books is not FAILED:
            texto = "; ".join(f"{b.get('isbn')} «{b.get('title')}»" for b in books) or "sin libros vinculados"
            self.ok(f"Libros del autor {aid}: {texto}")

    def vincular(self):
        aid = self._need_id()
        if aid is None or not self.need(self.link, "isbn"):
            return
        order = self.run(_int_or_none, self.link.get("author_order"))
        if order is FAILED:
            return
        data = self.run(self.app.api.link_author_book, aid, self.link.get("isbn"), order)
        if data is not FAILED:
            self.ok(data.get("message", "Vinculado."))
            self.listar(quiet=True)

    def desvincular(self):
        aid = self._need_id()
        if aid is None or not self.need(self.link, "isbn"):
            return
        data = self.run(self.app.api.unlink_author_book, aid, self.link.get("isbn"))
        if data is not FAILED:
            self.ok(data.get("message", "Desvinculado."))
            self.listar(quiet=True)


# ======================================================================
# PEDIDOS
# ======================================================================
class PedidosTab(CrudTab):
    COLUMNS = ("order_id", "user_id", "status", "total", "items_count", "created_at")

    def __init__(self, parent, app, on_pay):
        super().__init__(parent, app, "Microservicio PEDIDOS (puerto 5004, /pedidos). Todo exige JWT. customer crea y ve SOLO los suyos; "
                                      "staff/admin ven todos. Crear descuenta stock; cancelar lo repone. «pagado» solo lo marca Pagos.")
        self.on_pay = on_pay
        self.lines = []  # [{"isbn":..., "quantity":...}]
        left, right = ttk.Frame(self.body), ttk.Frame(self.body)
        left.pack(side="left", fill="both", expand=True)
        right.pack(side="left", fill="y", padx=(10, 0))
        bar = ttk.Frame(left)
        bar.grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(bar, text="Estado:").pack(side="left")
        self.filter = ttk.Combobox(bar, values=STATUS_CHOICES, width=11, state="readonly")
        self.filter.set("")
        self.filter.pack(side="left", padx=4)
        ttk.Button(bar, text="↻ Listar (GET /pedidos)", command=self.listar).pack(side="left", padx=2)
        self.tree = self.make_tree(left, self.COLUMNS, (60, 60, 90, 80, 70, 150), height=9)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.detail = tk.Text(left, height=8, wrap="word", state="disabled", background="#f6f6f6")
        self.detail.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.sel = Form(right, "Pedido seleccionado", [("order_id", "order_id", "entry")])
        self.sel.pack(fill="x")
        self.buttons(right, [
            ("Obtener (GET)", self.obtener), ("Cancelar (DELETE)", self.cancelar),
            ("Cancelar (PATCH status)", lambda: self.cambiar("cancelado")),
            ("Marcar enviado (PATCH)", lambda: self.cambiar("enviado")),
            ("Probar «pagado» (409)", lambda: self.cambiar("pagado")), ("Pagar este pedido →", self.pagar)],
            columns=2).pack(fill="x", pady=4)

        self.new = Form(right, "Nuevo pedido (POST /pedidos)", [("isbn", "ISBN", "entry"), ("quantity", "Cantidad", "entry"),
                                                                   ("user_id", "A nombre de (staff/admin)", "entry")])
        self.new.pack(fill="x", pady=(8, 0))
        self.new.set("quantity", "1")
        self.lines_box = tk.Listbox(right, height=4, width=44)
        self.lines_box.pack(fill="x", pady=4)
        self.buttons(right, [("Agregar línea", self.add_line), ("Quitar línea", self.remove_line),
                             ("Crear pedido (POST)", self.crear)], columns=3).pack(fill="x")
        self._loaded = False

    def on_shown(self):
        if not self._loaded:
            self._loaded = True
            self.listar(quiet=True)

    def _oid(self):
        text = self.sel.get("order_id")
        if not text.isdigit():
            self.msg.config(text="Escribe el order_id (o elige una fila).", foreground=BAD)
            return None
        return int(text)

    def _show_order(self, order):
        lines = [f"Pedido {order['order_id']} · usuario {order['user_id']} · {order['status']} · total {order['total']}"]
        lines += [f"  • {i['isbn']}  {i['title']}  × {i['quantity']}  @ {i['unit_price']}" for i in order.get("items", [])]
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", "\n".join(lines))
        self.detail.config(state="disabled")

    def on_select(self, _event=None):
        selection = self.tree.selection()
        if selection:
            self.sel.set("order_id", selection[0])
            order = self.run(self.app.api.get_order, int(selection[0]))
            if order is not FAILED:
                self._show_order(order)
                self.ok(f"Pedido {selection[0]} cargado.")

    def listar(self, quiet=False):
        orders = self.run(self.app.api.list_orders, self.filter.get() or None)
        if orders is FAILED:
            return
        self.fill_tree(self.tree, orders, "order_id", self.COLUMNS)
        if not quiet:
            self.ok(f"{len(orders)} pedido(s).")

    def obtener(self):
        oid = self._oid()
        if oid is None:
            return
        order = self.run(self.app.api.get_order, oid)
        if order is not FAILED:
            self._show_order(order)
            self.ok(f"Pedido {oid}: {order['status']}.")

    def cancelar(self):
        oid = self._oid()
        if oid is None or not messagebox.askyesno("Cancelar pedido", f"¿Cancelar el pedido {oid}? Se repone el stock."):
            return
        data = self.run(self.app.api.cancel_order, oid)
        if data is not FAILED:
            self._show_order(data["order"])
            self.ok(data.get("message", "Cancelado."))
            self.listar(quiet=True)

    def cambiar(self, status):
        oid = self._oid()
        if oid is None:
            return
        data = self.run(self.app.api.change_order_status, oid, status)
        if data is not FAILED:
            self._show_order(data["order"])
            self.ok(data.get("message", f"Pedido {status}."))
            self.listar(quiet=True)

    def pagar(self):
        oid = self._oid()
        if oid is None:
            return
        order = self.run(self.app.api.get_order, oid)
        if order is not FAILED:
            self.on_pay(order)

    def add_line(self):
        isbn, qty = self.new.get("isbn"), self.new.get("quantity")
        if not isbn or not qty.isdigit() or int(qty) < 1:
            return self.msg.config(text="Escribe un ISBN y una cantidad entera ≥ 1.", foreground=BAD)
        self.lines.append({"isbn": isbn, "quantity": int(qty)})
        self.lines_box.insert("end", f"{isbn}  ×  {qty}")
        self.new.clear(("isbn",))

    def remove_line(self):
        selection = self.lines_box.curselection()
        if selection:
            self.lines.pop(selection[0])
            self.lines_box.delete(selection[0])

    def crear(self):
        if not self.lines:
            return self.msg.config(text="Agrega al menos una línea (ISBN y cantidad).", foreground=BAD)
        uid = self.run(_int_or_none, self.new.get("user_id"))
        if uid is FAILED:
            return
        data = self.run(self.app.api.create_order, list(self.lines), uid)
        if data is not FAILED:
            order = data["order"]
            self.lines.clear()
            self.lines_box.delete(0, "end")
            self.sel.set("order_id", order["order_id"])
            self._show_order(order)
            self.ok(f"{data.get('message')} order_id={order['order_id']} total={order['total']}")
            self.listar(quiet=True)


# ======================================================================
# PAGOS
# ======================================================================
class PagosTab(CrudTab):
    COLUMNS = ("payment_id", "order_id", "user_id", "amount", "method", "status", "created_at")

    def __init__(self, parent, app):
        super().__init__(parent, app, "Microservicio PAGOS (puerto 5005, /pagos). Todo exige JWT. POST lleva la cabecera Idempotency-Key: "
                                      "reintentar con la MISMA clave no cobra dos veces (Idempotent-Replay). Los pagos son inmutables: "
                                      "PUT/PATCH/DELETE responden 405. Sin Redis no se cobra (503).")
        self.last_key = None
        left, right = ttk.Frame(self.body), ttk.Frame(self.body)
        left.pack(side="left", fill="both", expand=True)
        right.pack(side="left", fill="y", padx=(10, 0))
        bar = ttk.Frame(left)
        bar.grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(bar, text="order_id:").pack(side="left")
        self.filter = ttk.Entry(bar, width=8)
        self.filter.pack(side="left", padx=4)
        ttk.Button(bar, text="↻ Listar (GET /pagos)", command=self.listar).pack(side="left", padx=2)
        self.tree = self.make_tree(left, self.COLUMNS, (70, 70, 60, 80, 100, 80, 150))
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        self.form = Form(right, "Pago", [("payment_id", "payment_id (consulta)", "entry"), ("order_id", "order_id", "entry"),
                                         ("method", "Método", METHOD_CHOICES), ("amount", "Monto", "entry"),
                                         ("key", "Idempotency-Key", "entry")])
        self.form.pack(fill="x")
        self.new_key()
        self.buttons(right, [
            ("Registrar pago (POST)", self.pagar), ("Reintentar MISMA clave", self.reintentar),
            ("Nueva clave", self.new_key), ("Obtener (GET)", self.obtener),
            ("Probar PUT → 405", lambda: self.inmutable("PUT")), ("Probar DELETE → 405", lambda: self.inmutable("DELETE"))],
            columns=2).pack(fill="x", pady=6)
        self._loaded = False

    def on_shown(self):
        if not self._loaded:
            self._loaded = True
            self.listar(quiet=True)

    def prefill(self, order):
        """Llega desde Pedidos: «Pagar este pedido →»."""
        self.form.set("order_id", order["order_id"])
        self.form.set("amount", order["total"])
        self.new_key()
        self.info(f"Pedido {order['order_id']} ({order['status']}), total {order['total']}: elige el método y pulsa «Registrar pago».")

    def new_key(self):
        self.form.set("key", f"pago-{uuid.uuid4().hex[:16]}")

    def on_select(self, _event=None):
        selection = self.tree.selection()
        if selection:
            self.form.set("payment_id", selection[0])

    def listar(self, quiet=False):
        order = self.filter.get().strip()
        payments = self.run(self.app.api.list_payments, int(order) if order.isdigit() else None)
        if payments is FAILED:
            return
        self.fill_tree(self.tree, payments, "payment_id", self.COLUMNS)
        if not quiet:
            self.ok(f"{len(payments)} pago(s).")

    def obtener(self):
        pid = self.form.get("payment_id")
        if not pid.isdigit():
            return self.msg.config(text="Escribe el payment_id (o elige una fila).", foreground=BAD)
        payment = self.run(self.app.api.get_payment, int(pid))
        if payment is not FAILED:
            self.ok(f"Pago {pid}: pedido {payment['order_id']} · {payment['amount']} · {payment['method']} · "
                    f"{payment['status']} · pedido «{payment.get('order_status')}»")

    def _send(self, key):
        f = self.form
        if not self.need(f, "order_id", "amount") or not f.get("order_id").isdigit():
            return
        data = self.run(self.app.api.create_payment, int(f.get("order_id")), f.get("method"), f.get("amount"), key)
        if data is FAILED:
            return
        self.last_key = key
        payment = data["payment"]
        if self.app.api.last_headers.get("Idempotent-Replay") == "true":
            self.ok(f"Respuesta REPETIDA (Idempotent-Replay: true): NO se cobró otra vez. Pago {payment['payment_id']} original.")
        else:
            self.ok(f"{data.get('message')} payment_id={payment['payment_id']} · monto {payment['amount']}")
            self.new_key()  # el siguiente pago es otra operación: clave nueva
        self.listar(quiet=True)

    def pagar(self):
        self._send(self.form.get("key"))

    def reintentar(self):
        if not self.last_key:
            return self.msg.config(text="Todavía no hay un pago previo que reintentar.", foreground=BAD)
        self.form.set("key", self.last_key)
        self._send(self.last_key)

    def inmutable(self, verb):
        pid = self.form.get("payment_id")
        if not pid.isdigit():
            return self.msg.config(text="Escribe un payment_id existente (o elige una fila).", foreground=BAD)
        data = self.run(self.app.api.modify_payment, int(pid), verb)
        if data is not FAILED:
            self.ok("Inesperado: el servidor aceptó modificar un pago.")


# ======================================================================
# BITÁCORA DE PETICIONES
# ======================================================================
class BitacoraTab(ttk.Frame):
    """Cada petición HTTP que hace la app (método, servicio, ruta, código, ms). Nunca guarda cuerpos, contraseñas ni tokens."""
    COLUMNS = ("hora", "método", "servicio", "ruta", "estado", "ms", "nota")
    MAX_ROWS = 500

    def __init__(self, parent, app):
        super().__init__(parent, padding=8)
        self.app = app
        ttk.Label(self, text="Bitácora de peticiones HTTP de esta sesión (evidencia de qué microservicio atendió cada operación y con qué código). "
                             "Verde 2xx · naranja 4xx (401 sin token, 403 sin rol) · rojo 5xx/sin conexión (503 = Redis caído).",
                  foreground=MUTED, wraplength=1000, justify="left").pack(anchor="w")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Limpiar", command=self.clear).pack(side="left", padx=2)
        ttk.Button(bar, text="Guardar como CSV…", command=self.export).pack(side="left", padx=2)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=self.COLUMNS, show="headings", selectmode="browse")
        for col, width in zip(self.COLUMNS, (70, 70, 70, 330, 60, 60, 170)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.tree.tag_configure("ok", foreground=OK)
        self.tree.tag_configure("warn", foreground=WARN)
        self.tree.tag_configure("bad", foreground=BAD)

    def add(self, entry):
        status = entry["status"]
        tag = "ok" if 200 <= status < 300 else "warn" if 400 <= status < 500 else "bad"
        self.tree.insert("", 0, values=(entry["time"], entry["method"], entry["service"], entry["path"],
                                        status or "—", entry["ms"], entry["note"]), tags=(tag,))
        children = self.tree.get_children()
        if len(children) > self.MAX_ROWS:
            self.tree.delete(*children[self.MAX_ROWS:])

    def clear(self):
        self.tree.delete(*self.tree.get_children())

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="bitacora_peticiones.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(self.COLUMNS)
            for item in reversed(self.tree.get_children()):
                writer.writerow(self.tree.item(item, "values"))
        messagebox.showinfo("Bitácora", f"Guardada en:\n{path}")
