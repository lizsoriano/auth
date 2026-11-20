"""Cliente de escritorio (Tkinter) de los 6 microservicios: login (auth), books (soap), users,
authors, pedidos y pagos. Recorrido del código, de arriba hacia abajo:

  GUI (Tk/ttk) -> config.py (1 dirección: el gateway) -> api_client.py (HTTP/requests + JWT)
      -> login/sesión (LoginView, PerfilTab) -> catálogo y administración de libros (books)
      -> service_tabs.py (Users, Authors, Pedidos, Pagos y la bitácora de peticiones)
      -> comprobación de servicios con semáforos (EstadoTab)

No se conecta nunca a PostgreSQL ni a Redis directamente: todo pasa por
api_client.ApiClient, que solo habla HTTP con los microservicios.
"""
import queue
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

import config
import session_store
from api_client import REFRESH_MARGIN_SECONDS, ApiClient, ApiError
from service_tabs import AuthorsTab, BitacoraTab, PagosTab, PedidosTab, UsersTab

POLL_MS = 15000  # comprobación periódica del semáforo (punto 5)
TOKEN_TICK_MS = 1000  # reloj del JWT en la barra superior (cálculo local, sin red)
ROLE_NAMES = {1: "admin", 2: "staff", 3: "customer"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Biblioteca digital — cliente de escritorio")
        self.geometry("1180x760")
        self.minsize(1000, 640)

        self.cfg = config.load()
        self.api = ApiClient(self.cfg)
        self.user = None
        self.last_request = None  # última petición HTTP (la usan las pestañas para mostrar «GET … → 200»)
        self.api.listeners.append(self._remember_request)
        self._ui_queue = queue.SimpleQueue()  # los hilos de fondo NO tocan Tk: dejan aquí lo que el hilo principal debe hacer
        self._renewing = False
        self._next_renew = 0.0  # no insistir cada segundo si la renovación falla (p. ej. 503 con Redis caído)

        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)

        self.login_view = LoginView(self.container, self)
        self.main_view = MainView(self.container, self)
        self.api.listeners.append(lambda entry: self.call_soon(self.main_view.bitacora_tab.add, entry))

        self.after(100, self.try_restore_session)
        self.after(50, self._pump_ui)
        self.after(TOKEN_TICK_MS, self._token_tick)

    def _remember_request(self, entry):
        self.last_request = entry

    def call_soon(self, fn, *args):
        """Seguro desde cualquier hilo: ejecuta fn(*args) en el hilo principal de Tk."""
        self._ui_queue.put((fn, args))

    def _pump_ui(self):
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.after(50, self._pump_ui)

    # --------------------------------------------- JWT: reloj y renovación
    def _token_tick(self):
        """Cada segundo: actualiza el reloj del JWT; si faltan < 3 min, lo renueva en segundo plano (sin congelar la GUI)."""
        if self.user is not None:
            self.main_view.update_token_clock()
            if (self.api.jwt_token and not self._renewing and time.monotonic() >= self._next_renew
                    and self.api.seconds_left() < REFRESH_MARGIN_SECONDS):
                self._renewing = True
                self._next_renew = time.monotonic() + 15
                threading.Thread(target=self._renew_in_background, daemon=True).start()
        self.after(TOKEN_TICK_MS, self._token_tick)

    def _renew_in_background(self):
        renewed = self.api.ensure_fresh()
        self.call_soon(self._after_renew, renewed)

    def _after_renew(self, renewed):
        self._renewing = False
        if self.user is not None and not self.api.jwt_token:  # el refresh ya no sirve: sesión perdida
            messagebox.showwarning("Sesión vencida", "No se pudo renovar el JWT (la sesión caducó o se cerró). Inicia sesión de nuevo.")
            self.on_logout()

    # --------------------------------------------------------- navegación
    def show_login(self):
        self.main_view.pack_forget()
        self.login_view.pack(fill="both", expand=True)

    def show_main(self):
        self.login_view.pack_forget()
        self.main_view.pack(fill="both", expand=True)
        self.main_view.on_shown()

    # ------------------------------------------------- sesión al arrancar
    def try_restore_session(self):
        """Punto 3: recordar al usuario NO significa que la sesión siga vigente. El JWT y el refresh token viven
        solo en memoria (nunca en disco), así que al reabrir la app se pide la contraseña otra vez; el correo
        recordado se precarga y la cookie vieja se revalida/limpia contra el servidor."""
        remembered = session_store.load_email()
        if remembered:
            try:
                self.api.get_session()  # solo para comprobar si la cookie sigue viva en el servidor
            except ApiError:
                pass
            self.login_view.prefill(remembered, "Tu correo se recordó, pero por seguridad el JWT no se guarda en disco: "
                                                "escribe tu contraseña para entrar.")
        self.show_login()

    def on_login_success(self, data):
        self.user = data["user"]
        self.show_main()

    def on_logout(self):
        try:
            self.api.logout()
        except ApiError:
            pass  # aunque falle la llamada, se limpia la sesión local igual
        self.user = None
        self.show_login()

    def urls_changed(self):
        self.cfg = config.load()
        self.api.set_urls(self.cfg)

    def role_label(self):
        claims = self.api.token_claims()
        role_id = claims.get("role_id", (self.user or {}).get("role_id"))
        return f"{ROLE_NAMES.get(role_id, '?')} (role_id {role_id})"


# ======================================================================
# LOGIN (punto 2)
# ======================================================================
class LoginView(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent)
        self.app = app
        wrap = ttk.Frame(self, padding=30)
        wrap.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(wrap, text="Iniciar sesión", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 14))

        ttk.Label(wrap, text="Email").grid(row=1, column=0, sticky="w")
        self.email = ttk.Entry(wrap, width=32)
        self.email.grid(row=1, column=1, pady=4)

        ttk.Label(wrap, text="Password").grid(row=2, column=0, sticky="w")
        self.password = ttk.Entry(wrap, width=32, show="•")
        self.password.grid(row=2, column=1, pady=4)
        self.password.bind("<Return>", lambda _e: self.do_login())

        ttk.Button(wrap, text="Entrar", command=self.do_login).grid(row=3, column=0, columnspan=2, pady=(10, 4), sticky="ew")
        ttk.Button(wrap, text="Registrarse", command=self.open_register).grid(row=4, column=0, columnspan=2, sticky="ew")

        self.error_label = ttk.Label(wrap, text="", foreground="#b00020", wraplength=320)
        self.error_label.grid(row=5, column=0, columnspan=2, pady=(10, 0))

    def prefill(self, email, message=""):
        self.email.delete(0, "end")
        self.email.insert(0, email)
        self.error_label.config(text=message, foreground="#555555")
        self.password.focus_set()

    def do_login(self):
        self.error_label.config(text="", foreground="#b00020")
        email, password = self.email.get().strip(), self.password.get()
        if not email or not password:
            self.error_label.config(text="Escribe tu email y tu contraseña.")
            return
        try:
            data = self.app.api.login(email, password)
        except ApiError as exc:
            # Distingue credenciales incorrectas de cuenta aún sin confirmar
            # (dos casos explícitos del punto 2 del enunciado).
            self.error_label.config(text=exc.message)
            return
        self.password.delete(0, "end")
        self.app.on_login_success(data)

    def open_register(self):
        RegisterDialog(self, self.app)


class RegisterDialog(tk.Toplevel):
    def __init__(self, parent, app: App):
        super().__init__(parent)
        self.app = app
        self.title("Registrarse")
        self.resizable(False, False)
        fields = [("Nombre", "nombre"), ("Apellido paterno", "apellido_paterno"),
                  ("Apellido materno", "apellido_materno"), ("Email", "email"), ("Password", "password")]
        self.vars = {}
        for i, (label, key) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=10, pady=4)
            entry = ttk.Entry(self, width=30, show="•" if key == "password" else "")
            entry.grid(row=i, column=1, padx=10, pady=4)
            self.vars[key] = entry
        self.info = ttk.Label(self, text="", wraplength=300)
        self.info.grid(row=len(fields), column=0, columnspan=2, padx=10, pady=6)
        ttk.Button(self, text="Crear cuenta", command=self.submit).grid(row=len(fields) + 1, column=0, columnspan=2, pady=8, sticky="ew")

    def submit(self):
        valores = {k: e.get().strip() for k, e in self.vars.items()}
        try:
            data = self.app.api.register(**valores)
        except ApiError as exc:
            self.info.config(text=exc.message, foreground="#b00020")
            return
        self.info.config(text=data.get("message", "Cuenta creada."), foreground="#0a7a2a")
        self.after(1800, self.destroy)


# ======================================================================
# PANEL PRINCIPAL (punto 4): Perfil · Catálogo · Administración · Estado · Config
# ======================================================================
class MainView(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent)
        self.app = app

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.user_label = ttk.Label(top, text="", font=("Segoe UI", 10, "bold"))
        self.user_label.pack(side="left")
        ttk.Button(top, text="Cerrar sesión", command=self.app.on_logout).pack(side="right")
        ttk.Button(top, text="Renovar JWT ahora", command=self.renew_now).pack(side="right", padx=6)
        self.token_label = ttk.Label(top, text="JWT: —", font=("Consolas", 10))
        self.token_label.pack(side="right", padx=10)

        self.notebook = notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.perfil_tab = PerfilTab(notebook, app)
        self.catalogo_tab = CatalogoTab(notebook, app)
        self.admin_tab = AdminTab(notebook, app, on_change=lambda: self.catalogo_tab.load())
        self.authors_tab = AuthorsTab(notebook, app)
        self.users_tab = UsersTab(notebook, app)
        self.pagos_tab = PagosTab(notebook, app)
        self.pedidos_tab = PedidosTab(notebook, app, on_pay=self.go_pay)
        self.estado_tab = EstadoTab(notebook, app)
        self.bitacora_tab = BitacoraTab(notebook, app)
        self.config_tab = ConfigTab(notebook, app)

        self.tabs = {
            "catalogo": (self.catalogo_tab, "Catálogo de libros"),
            "libros": (self.admin_tab, "Libros (books)"),
            "autores": (self.authors_tab, "Autores (authors)"),
            "usuarios": (self.users_tab, "Usuarios (users)"),
            "pedidos": (self.pedidos_tab, "Pedidos"),
            "pagos": (self.pagos_tab, "Pagos"),
            "perfil": (self.perfil_tab, "Sesión y perfil"),
            "estado": (self.estado_tab, "Semáforos"),
            "bitacora": (self.bitacora_tab, "Bitácora HTTP"),
            "config": (self.config_tab, "Configuración"),
        }
        for tab, text in self.tabs.values():
            notebook.add(tab, text=text)
        notebook.bind("<<NotebookTabChanged>>", self._tab_changed)

    def _tab_changed(self, _event=None):
        tab = self.nametowidget(self.notebook.select())
        if hasattr(tab, "on_shown"):
            tab.on_shown()

    def go_pay(self, order):
        """Pedidos -> Pagos: abre la pestaña de pagos con el pedido y su total ya capturados."""
        self.pagos_tab.prefill(order)
        self.notebook.select(self.pagos_tab)

    # ---- reloj del JWT (se actualiza cada segundo desde App._token_tick; no usa la red)
    def update_token_clock(self):
        seconds = self.app.api.seconds_left()
        if not self.app.api.jwt_token:
            self.token_label.config(text="JWT: sin token", foreground="#b00020")
            return
        color = "#0a7a2a" if seconds >= REFRESH_MARGIN_SECONDS else "#b36b00"
        self.token_label.config(text=f"JWT expira en {seconds // 60:02d}:{seconds % 60:02d}", foreground=color)

    def renew_now(self):
        try:
            self.app.api.refresh_now()
        except ApiError as exc:
            if exc.status in (400, 401):
                messagebox.showwarning("Sesión vencida", exc.message + "\n\nInicia sesión de nuevo.")
                self.app.on_logout()
            else:
                messagebox.showerror("No se pudo renovar el JWT", exc.message)
            return
        self.update_token_clock()
        messagebox.showinfo("JWT renovado", "Nuevo JWT de 20 minutos. El refresh token anterior ya no sirve (un solo uso).")

    def on_shown(self):
        self.user_label.config(text=f"{self.app.user.get('email', '')} · rol {self.app.role_label()}")
        self.update_token_clock()
        self.perfil_tab.refresh()
        self.catalogo_tab.load()
        self.estado_tab.start_polling()


# ---------------------------------------------------------------- Perfil
class PerfilTab(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, padding=16)
        self.app = app

        info = ttk.LabelFrame(self, text="Datos de la cuenta", padding=12)
        info.pack(fill="x", pady=(0, 12))
        self.info_vars = {k: tk.StringVar() for k in ("nombre", "apellidos", "email", "verificado", "creado")}
        for i, (label, key) in enumerate([("Nombre", "nombre"), ("Apellidos", "apellidos"), ("Email", "email"),
                                          ("Correo verificado", "verificado"), ("Cuenta creada", "creado")]):
            ttk.Label(info, text=label + ":").grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(info, textvariable=self.info_vars[key]).grid(row=i, column=1, sticky="w", padx=8)

        session_box = ttk.LabelFrame(self, text="Sesión", padding=12)
        session_box.pack(fill="x", pady=(0, 12))
        self.session_var = tk.StringVar()
        ttk.Label(session_box, textvariable=self.session_var).pack(side="left")
        ttk.Button(session_box, text="Extender sesión 30 min", command=self.extend_session).pack(side="right")

        edit = ttk.LabelFrame(self, text="Modificar perfil (PATCH /profile — solo se envía lo que llenes)", padding=12)
        edit.pack(fill="x")
        self.edit_vars = {}
        for i, (label, key) in enumerate([("Nombre", "nombre"), ("Apellido paterno", "apellido_paterno"),
                                          ("Apellido materno", "apellido_materno"), ("Nuevo email", "email"),
                                          ("Nueva password", "password")]):
            ttk.Label(edit, text=label).grid(row=i, column=0, sticky="w", pady=2)
            entry = ttk.Entry(edit, width=30, show="•" if key == "password" else "")
            entry.grid(row=i, column=1, pady=2, padx=6)
            self.edit_vars[key] = entry
        ttk.Button(edit, text="Guardar cambios", command=self.save_profile).grid(row=5, column=0, columnspan=2, pady=8, sticky="ew")
        self.edit_msg = ttk.Label(edit, text="", wraplength=400)
        self.edit_msg.grid(row=6, column=0, columnspan=2)

    def refresh(self):
        try:
            data = self.app.api.get_session()
        except ApiError as exc:
            self._handle_session_error(exc)
            return
        user = data["user"]
        self.info_vars["nombre"].set(user.get("nombre") or "(sin datos, cuenta creada por el monolito)")
        self.info_vars["apellidos"].set(" ".join(filter(None, [user.get("apellido_paterno"), user.get("apellido_materno")])) or "—")
        self.info_vars["email"].set(user.get("email", ""))
        self.info_vars["verificado"].set("Sí" if user.get("email_verified") else "No")
        self.info_vars["creado"].set(str(user.get("created_at", ""))[:19])
        segundos = data["session"]["expires_in_seconds"]
        aviso = "  ⚠ está por caducar" if segundos < 300 else ""
        self.session_var.set(f"Expira en {segundos // 60} min {segundos % 60} s{aviso}")

    def _handle_session_error(self, exc: ApiError):
        if exc.status == 401:
            messagebox.showwarning("Sesión caducada", exc.message)
            self.app.on_logout()
        else:
            messagebox.showerror("Error", exc.message)

    def extend_session(self):
        try:
            self.app.api.extend_session()
        except ApiError as exc:
            self._handle_session_error(exc)
            return
        self.refresh()

    def save_profile(self):
        campos = {k: e.get().strip() for k, e in self.edit_vars.items()}
        self.edit_msg.config(text="")
        try:
            result = self.app.api.update_profile(**campos)
        except ApiError as exc:
            self.edit_msg.config(text=exc.message, foreground="#b00020")
            return
        if result is None:
            self.edit_msg.config(text="No llenaste ningún campo.", foreground="#b00020")
            return
        for e in self.edit_vars.values():
            e.delete(0, "end")
        self.edit_msg.config(text=result.get("message", "Perfil actualizado."), foreground="#0a7a2a")
        self.refresh()


# --------------------------------------------------------------- Catálogo
class CatalogoTab(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, padding=10)
        self.app = app
        self.books = []

        filtros = ttk.LabelFrame(self, text="Buscar / filtrar", padding=8)
        filtros.pack(fill="x", pady=(0, 8))
        self.f_isbn = self._campo(filtros, "ISBN", 0)
        self.f_titulo = self._campo(filtros, "Título", 1)
        self.f_anio = self._campo(filtros, "Año", 2, width=8)
        self.f_min = self._campo(filtros, "Precio mín.", 3, width=8)
        self.f_max = self._campo(filtros, "Precio máx.", 4, width=8)
        ttk.Button(filtros, text="Filtrar", command=self.apply_filter).grid(row=0, column=10, padx=6)
        ttk.Button(filtros, text="Limpiar", command=self.clear_filter).grid(row=0, column=11, padx=6)
        ttk.Button(filtros, text="↻ Actualizar", command=self.load).grid(row=0, column=12, padx=6)

        cols = ("isbn", "title", "authors", "category", "year", "price", "stock")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        for c, w in zip(cols, (130, 220, 180, 110, 60, 80, 60)):
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.show_detail())

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=6)
        ttk.Button(bottom, text="Ver detalle", command=self.show_detail).pack(side="left")
        self.status = ttk.Label(bottom, text="")
        self.status.pack(side="right")

    def _campo(self, parent, label, col, width=14):
        ttk.Label(parent, text=label).grid(row=0, column=col * 2, padx=(6, 2))
        entry = ttk.Entry(parent, width=width)
        entry.grid(row=0, column=col * 2 + 1)
        return entry

    def load(self):
        self.status.config(text="Cargando…")
        try:
            self.books = self.app.api.list_books()
        except ApiError as exc:
            self.status.config(text=exc.message)
            messagebox.showerror("No se pudo cargar el catálogo", exc.message)
            return
        self.status.config(text=f"{len(self.books)} libro(s)")
        self._render(self.books)

    def _render(self, books):
        self.tree.delete(*self.tree.get_children())
        for b in books:
            self.tree.insert("", "end", iid=b["isbn"], values=(
                b["isbn"], b["title"], b.get("authors", ""), b.get("category", ""),
                b.get("publicationYear", ""), b.get("price", ""), b.get("stock", "")))

    def apply_filter(self):
        isbn, titulo, anio = self.f_isbn.get().strip(), self.f_titulo.get().strip().lower(), self.f_anio.get().strip()
        pmin, pmax = self.f_min.get().strip(), self.f_max.get().strip()
        result = self.books
        if isbn:
            result = [b for b in result if isbn in b["isbn"]]
        if titulo:
            result = [b for b in result if titulo in b["title"].lower()]
        if anio:
            result = [b for b in result if str(b.get("publicationYear")) == anio]
        if pmin:
            result = [b for b in result if float(b.get("price", 0)) >= float(pmin)]
        if pmax:
            result = [b for b in result if float(b.get("price", 0)) <= float(pmax)]
        self._render(result)
        self.status.config(text=f"{len(result)} de {len(self.books)} libro(s)")

    def clear_filter(self):
        for e in (self.f_isbn, self.f_titulo, self.f_anio, self.f_min, self.f_max):
            e.delete(0, "end")
        self._render(self.books)
        self.status.config(text=f"{len(self.books)} libro(s)")

    def show_detail(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Detalle", "Selecciona un libro primero.")
            return
        isbn = selection[0]
        try:
            libro = self.app.api.get_book(isbn)  # GET /books/{isbn}
            conceptos = [c for c in self.app.api.list_concepts() if c.get("isbn") == isbn]
            imagenes = next((b for b in self.app.api.list_images() if b.get("isbn") == isbn), None)
        except ApiError as exc:
            messagebox.showerror("No se pudo consultar el libro", exc.message)
            return
        BookDetailDialog(self, libro, conceptos, imagenes)


class BookDetailDialog(tk.Toplevel):
    def __init__(self, parent, libro, conceptos, imagenes):
        super().__init__(parent)
        self.title(f"Detalle — {libro['title']}")
        self.geometry("480x420")
        text = tk.Text(self, wrap="word")
        text.pack(fill="both", expand=True, padx=10, pady=10)
        for campo in ("isbn", "title", "authors", "category", "publicationYear", "price", "stock"):
            text.insert("end", f"{campo}: {libro.get(campo, '')}\n")
        text.insert("end", "\n-- Imágenes --\n")
        if imagenes and imagenes.get("images"):
            for img in imagenes["images"]:
                marca = " (portada)" if img.get("is_cover") or img.get("isCover") else ""
                text.insert("end", f"{img.get('url')}{marca}\n")
            ttk.Button(self, text="Abrir portada en el navegador",
                       command=lambda: webbrowser.open(imagenes["images"][0]["url"])).pack(pady=(0, 8))
        else:
            text.insert("end", "Este libro no tiene imágenes registradas.\n")
        text.insert("end", "\n-- Conceptos asociados --\n")
        if conceptos:
            for c in conceptos:
                text.insert("end", f"• {c.get('concept')}: {c.get('definition')}\n")
        else:
            text.insert("end", "Sin conceptos asociados.\n")
        text.config(state="disabled")


# ----------------------------------------------------------- Administración
class AdminTab(ttk.Frame):
    """CRUD (punto 10). Deja explícito qué método HTTP usa cada botón para
    poder explicar, como pide el enunciado (#11), la diferencia entre un
    PUT (reemplazo completo, todos los campos) y un PATCH (solo el campo
    que se llenó, el resto se conserva en el servidor)."""

    CAMPOS = [("ISBN", "isbn"), ("Título", "title"), ("Año", "publicationYear"), ("Precio", "price"),
              ("Stock", "stock"), ("Categoría", "category"), ("Formato", "format"), ("Autor(es)", "authors")]

    def __init__(self, parent, app: App, on_change):
        super().__init__(parent, padding=16)
        self.app = app
        self.on_change = on_change
        self.vars = {}
        for i, (label, key) in enumerate(self.CAMPOS):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", pady=3)
            entry = ttk.Entry(self, width=40)
            entry.grid(row=i, column=1, pady=3, padx=8, sticky="w")
            self.vars[key] = entry

        ttk.Label(self, text="(Para PATCH: deja vacío lo que NO quieras cambiar)",
                  foreground="#666").grid(row=len(self.CAMPOS), column=0, columnspan=2, sticky="w")

        botones = ttk.Frame(self)
        botones.grid(row=len(self.CAMPOS) + 1, column=0, columnspan=2, pady=10, sticky="ew")
        ttk.Button(botones, text="Crear (POST)", command=self.crear).pack(side="left", padx=4)
        ttk.Button(botones, text="Reemplazar completo (PUT)", command=self.reemplazar).pack(side="left", padx=4)
        ttk.Button(botones, text="Modificar parcial (PATCH)", command=self.parchear).pack(side="left", padx=4)
        ttk.Button(botones, text="Eliminar (DELETE)", command=self.eliminar).pack(side="left", padx=4)
        ttk.Button(botones, text="Cargar por ISBN (GET)", command=self.cargar).pack(side="left", padx=4)

        self.msg = ttk.Label(self, text="", wraplength=500)
        self.msg.grid(row=len(self.CAMPOS) + 2, column=0, columnspan=2, sticky="w")

    def _valores(self):
        return {k: e.get().strip() for k, e in self.vars.items()}

    def _mostrar(self, texto, ok=True):
        self.msg.config(text=texto, foreground="#0a7a2a" if ok else "#b00020")

    def cargar(self):
        isbn = self.vars["isbn"].get().strip()
        if not isbn:
            self._mostrar("Escribe un ISBN para cargar.", ok=False)
            return
        try:
            libro = self.app.api.get_book(isbn)
        except ApiError as exc:
            self._mostrar(exc.message, ok=False)
            return
        for key, _ in self.CAMPOS:
            if key in libro:
                self.vars[key].delete(0, "end")
                self.vars[key].insert(0, str(libro[key]))
        self._mostrar(f"Libro {isbn} cargado.")

    def crear(self):
        v = self._valores()
        try:
            data = self.app.api.create_book(**v)
        except ApiError as exc:
            self._mostrar(exc.message, ok=False)  # p. ej. "Ya existe un libro con isbn ..." (409)
            return
        self._mostrar(f"Creado: {data}")
        self.on_change()

    def reemplazar(self):
        v = self._valores()
        isbn = v.pop("isbn")
        try:
            data = self.app.api.replace_book(isbn, **v)
        except ApiError as exc:
            self._mostrar(exc.message, ok=False)
            return
        self._mostrar(data.get("message", "Reemplazado."))
        self.on_change()

    def parchear(self):
        v = self._valores()
        isbn = v.pop("isbn")
        enviados = {k: val for k, val in v.items() if val}
        if not enviados:
            self._mostrar("Llena al menos un campo (además del ISBN) para el PATCH.", ok=False)
            return
        try:
            data = self.app.api.patch_book(isbn, **v)
        except ApiError as exc:
            self._mostrar(exc.message, ok=False)
            return
        self._mostrar(f"{data.get('message', 'Modificado.')}  (solo se enviaron: {', '.join(enviados)})")
        self.on_change()

    def eliminar(self):
        isbn = self.vars["isbn"].get().strip()
        if not isbn:
            self._mostrar("Escribe un ISBN para eliminar.", ok=False)
            return
        if not messagebox.askyesno("Confirmar eliminación", f"¿Eliminar el libro con ISBN {isbn}? Esta acción no se puede deshacer."):
            return
        try:
            data = self.app.api.delete_book(isbn)
        except ApiError as exc:
            self._mostrar(exc.message, ok=False)
            return
        self._mostrar(data.get("message", "Eliminado."))
        self.on_change()


# -------------------------------------------------------- Estado (semáforo)
class EstadoTab(ttk.Frame):
    COLORES = {"green": "#1e8e3e", "yellow": "#e8a300", "red": "#c5221f", "grey": "#999999"}
    ETIQUETAS = {"green": "Arriba", "yellow": "Degradado", "red": "Caído", "grey": "Sin comprobar"}

    def __init__(self, parent, app: App):
        super().__init__(parent, padding=16)
        self.app = app
        self._after_id = None
        self.rows = {}
        ttk.Label(self, text="Cada microservicio es independiente (otro proceso, otro puerto, su propio rol de PostgreSQL). "
                             "Verde = el servicio, PostgreSQL y Redis responden · amarillo = el servicio responde pero Redis (o PostgreSQL) no · "
                             "rojo = no responde.", foreground="#666", wraplength=1000, justify="left").grid(row=0, column=0, columnspan=4, sticky="w")
        keys = list(config.KEYS) + ["redis"]
        for i, key in enumerate(keys):
            label = "Redis (compartido)" if key == "redis" else f"{config.SERVICES[key][0]} /{config.SERVICES[key][1]}"
            box = ttk.LabelFrame(self, text=label, padding=10)
            box.grid(row=1 + i // 4, column=i % 4, padx=8, pady=8, sticky="nsew")
            dot = tk.Label(box, text="●", font=("Segoe UI", 26), fg=self.COLORES["grey"])
            dot.pack()
            text = ttk.Label(box, text="Sin comprobar", wraplength=210, justify="center")
            text.pack(pady=4)
            last = ttk.Label(box, text="", foreground="#666")
            last.pack()
            self.rows[key] = {"dot": dot, "text": text, "last": last}
        for col in range(4):
            self.columnconfigure(col, weight=1)
        ttk.Button(self, text="Comprobar ahora", command=self.check_now).grid(row=4, column=0, columnspan=4, pady=12)

    def start_polling(self):
        self.check_now()

    def on_shown(self):
        self.check_now()

    def check_now(self):
        threading.Thread(target=self._check_in_background, daemon=True).start()

    def _check_in_background(self):
        results = {key: self.app.api.health(self.app.api.url_of(key)) for key in config.KEYS}
        self.app.call_soon(self._update_ui, results)

    def _redis_summary(self, results):
        seen = [redis for (_c, _m, redis) in results.values() if redis]
        if not seen:
            return "grey", "Ningún servicio respondió: no se puede saber"
        bad = seen.count("unavailable")
        if bad == 0:
            return "green", f"Responde (visto por {len(seen)} servicio(s))"
        if bad == len(seen):
            return "red", f"NO responde (lo reportan {bad} servicio(s)): sesión, revocación y pagos fallan cerrado (503)"
        return "yellow", f"Responde para {len(seen) - bad} y falla para {bad} servicio(s)"

    def _update_ui(self, results):
        now = datetime.now().strftime("%H:%M:%S")
        shown = {key: (estado, mensaje) for key, (estado, mensaje, _r) in results.items()}
        shown["redis"] = self._redis_summary(results)
        for key, (estado, mensaje) in shown.items():
            row = self.rows[key]
            row["dot"].config(fg=self.COLORES[estado])
            row["text"].config(text=f"{self.ETIQUETAS[estado]}\n{mensaje}")
            row["last"].config(text=f"Última comprobación: {now}")
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(POLL_MS, self.check_now)


# ------------------------------------------------------------- Configuración
class ConfigTab(ttk.Frame):
    """Una sola dirección: la del API Gateway. Cada microservicio es una ruta de ella."""

    def __init__(self, parent, app: App):
        super().__init__(parent, padding=20)
        self.app = app
        ttk.Label(self, text="Dirección del gateway").grid(row=0, column=0, sticky="w", pady=3)
        self.gateway = ttk.Entry(self, width=50)
        self.gateway.grid(row=0, column=1, padx=8)
        self.gateway.insert(0, app.cfg.get("gateway_url") or config.DEFAULT_GATEWAY)

        self.rutas = ttk.Label(self, text="", foreground="#444", justify="left")
        self.rutas.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.gateway.bind("<KeyRelease>", lambda _e: self._mostrar_rutas())

        botones = ttk.Frame(self)
        botones.grid(row=2, column=0, columnspan=2, pady=10, sticky="w")
        ttk.Button(botones, text="Esta computadora (localhost:8080)", command=self.usar_local).pack(side="left", padx=4)
        ttk.Button(botones, text="Probar conexión", command=self.probar).pack(side="left", padx=4)
        ttk.Button(botones, text="Guardar", command=self.guardar).pack(side="left", padx=4)
        ttk.Button(botones, text="Restaurar valores predeterminados", command=self.restaurar).pack(side="left", padx=4)

        self.msg = ttk.Label(self, text="", wraplength=700, justify="left")
        self.msg.grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(self, text="Local: el gateway de esta computadora (http://localhost:8080).\n"
                             "Instancia de GCP: basta la IP, por ejemplo 34.51.109.238 (Nginx en el puerto 80 -> gateway -> servicios).\n"
                             "La IP externa de la VM cambia cada vez que se enciende.",
                  foreground="#666").grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self._mostrar_rutas()

    def _urls(self):
        return config.gateway_urls(self.gateway.get())

    def _mostrar_rutas(self):
        urls = self._urls()
        self.rutas.config(text="\n".join(f"{config.SERVICES[k][0]:8} {u}" for k, u in urls.items()))

    def _set_gateway(self, base):
        self.gateway.delete(0, "end")
        self.gateway.insert(0, base)
        self._mostrar_rutas()

    def usar_local(self):
        self._set_gateway(config.DEFAULT_GATEWAY)
        self.msg.config(text="Gateway de esta computadora aplicado (falta Guardar).", foreground="#0a7a2a")

    def probar(self):
        urls = {f"{k}_url": v for k, v in self._urls().items()}
        self.msg.config(text="Probando…", foreground="#666")
        threading.Thread(target=self._probar_bg, args=(urls,), daemon=True).start()

    def _probar_bg(self, urls):
        temp = ApiClient(urls)
        results = {key: temp.health(temp.url_of(key)) for key in config.KEYS}
        self.app.call_soon(self._probar_done, results)

    def _probar_done(self, results):
        lines = [f"{key.upper():8} {estado:6} — {mensaje}" for key, (estado, mensaje, _r) in results.items()]
        todo_rojo = all(estado == "red" for estado, _m, _r in results.values())
        self.msg.config(text="\n".join(lines), foreground="#b00020" if todo_rojo else "#0a7a2a")

    def guardar(self):
        base = config.normalize_gateway(self.gateway.get())
        if not base.startswith(("http://", "https://")):
            self.msg.config(text="La dirección debe empezar con http:// o https://", foreground="#b00020")
            return
        config.save({"gateway_url": base})
        self._set_gateway(base)
        self.app.urls_changed()
        self.msg.config(text="Configuración guardada.", foreground="#0a7a2a")

    def restaurar(self):
        nuevo = config.restore_defaults()
        self._set_gateway(nuevo["gateway_url"])
        self.app.urls_changed()
        self.msg.config(text="Restaurados los valores predeterminados.", foreground="#0a7a2a")


if __name__ == "__main__":
    App().mainloop()
