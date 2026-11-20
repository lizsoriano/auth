"""Comunicación HTTP con los 6 microservicios: login (auth), books (soap), users, authors, pedidos y pagos.

Único módulo que sabe de `requests`/HTTP; la GUI nunca arma una URL ni
lee un `response.status_code` directamente -- llama a estos métodos y
recibe datos ya interpretados, o un ApiError con un mensaje entendible
(nunca un traceback crudo, punto 12 del enunciado).

JWT: `POST /login` entrega un JWT de 20 min y un refresh token (de un solo uso). El cliente los guarda SOLO en
memoria (nunca en disco), manda `Authorization: Bearer <jwt>` en cada petición y lo renueva con
`POST /token/refresh` ANTES de que caduque (o, si un servicio responde 401, una vez y reintenta).
"""
import base64
import json
import threading
import time

import requests

import config
import session_store

TIMEOUT = 8
REFRESH_MARGIN_SECONDS = 180  # se renueva cuando faltan menos de 3 min de los 20


class ApiError(Exception):
    """status=0 -> no hubo respuesta del servidor (caído/URL mala/timeout).
    status>0  -> el servidor sí respondió, con ese código HTTP."""

    def __init__(self, message, status=0, code=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class ApiClient:
    def __init__(self, urls):
        self.urls = {}
        self.set_urls(urls)
        self.session = requests.Session()
        self.session.cookies = session_store.cookie_jar()
        self.session.headers.update({"Accept": "application/json"})
        self.jwt_token = None
        self.refresh_token = None
        self._deadline = 0.0  # time.monotonic() en que caduca el JWT (no depende del reloj del servidor)
        self._refresh_lock = threading.Lock()
        self.last_headers = {}
        self.listeners = []  # funciones(entry) que reciben cada petición (para la bitácora de la GUI)

    # ------------------------------------------------------------- URLs
    def set_urls(self, urls):
        self.urls = {key: str(urls[f"{key}_url"]).rstrip("/") for key in config.KEYS}

    def url_of(self, service):
        return self.urls[service]

    @property
    def auth_url(self):
        return self.urls["auth"]

    @property
    def books_url(self):
        return self.urls["books"]

    # --------------------------------------------------------------- JWT
    def _set_tokens(self, data):
        self.jwt_token = data.get("token")
        self.refresh_token = data.get("refresh_token")
        self._deadline = time.monotonic() + float(data.get("token_expires_in_seconds") or 1200)

    def _clear_tokens(self):
        self.jwt_token = self.refresh_token = None
        self._deadline = 0.0

    def seconds_left(self):
        """Segundos de vida que le quedan al JWT (0 si no hay)."""
        return max(0, int(self._deadline - time.monotonic())) if self.jwt_token else 0

    def token_claims(self):
        """Claims del JWT para MOSTRARLOS (user_id, role_id, role, exp). Solo lectura: la firma la valida el servidor."""
        if not self.jwt_token:
            return {}
        try:
            payload = self.jwt_token.split(".")[1]
            return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except (IndexError, ValueError):
            return {}

    def ensure_fresh(self):
        """Renueva el JWT si le quedan menos de REFRESH_MARGIN_SECONDS. True = se renovó, False = no hizo falta/no se pudo."""
        if self.jwt_token and self.refresh_token and self.seconds_left() < REFRESH_MARGIN_SECONDS:
            return self._try_refresh()
        return False

    def refresh_now(self):
        """Botón «Renovar JWT ahora»: igual que la renovación automática pero los errores sí se muestran."""
        if not self.refresh_token:
            raise ApiError("No hay refresh token: inicia sesión de nuevo.", 401, "no_refresh_token")
        with self._refresh_lock:
            data = self._request("POST", "auth", "/token/refresh", {"refresh_token": self.refresh_token}, auth=False)
            self._set_tokens(data)
        return data

    def _try_refresh(self):
        with self._refresh_lock:
            if not self.refresh_token:
                return False
            try:
                data = self._request("POST", "auth", "/token/refresh", {"refresh_token": self.refresh_token}, auth=False)
            except ApiError as exc:
                if exc.status in (400, 401):  # refresh vencido, usado o sesión cerrada: ya no sirve de nada
                    self._clear_tokens()
                return False
            self._set_tokens(data)
            return True

    # ------------------------------------------------------------- interno
    def _emit(self, method, service, path, status, started, note=""):
        entry = {"time": time.strftime("%H:%M:%S"), "method": method, "service": service, "path": path,
                 "status": status, "ms": int((time.monotonic() - started) * 1000), "note": note}
        for listener in list(self.listeners):
            try:
                listener(entry)
            except Exception:  # noqa: BLE001 - la bitácora nunca debe romper una petición
                pass

    def _request(self, method, service, path, json_body=None, params=None, headers=None, auth=True, _retry=True):
        if auth and self.jwt_token:
            self.ensure_fresh()
        url = f"{self.urls[service]}{path}"
        send_headers = dict(headers or {})
        if auth and self.jwt_token:
            send_headers["Authorization"] = f"Bearer {self.jwt_token}"
        started = time.monotonic()
        try:
            response = self.session.request(method, url, json=json_body, params={"format": "json", **(params or {})},
                                            headers=send_headers, timeout=TIMEOUT)
        except requests.exceptions.ConnectionError:
            self._emit(method, service, path, 0, started, "sin conexión")
            raise ApiError("No se pudo conectar con el servidor. Revisa la URL en Configuración "
                           "o si el microservicio está encendido.")
        except requests.exceptions.Timeout:
            self._emit(method, service, path, 0, started, "tiempo agotado")
            raise ApiError("El servidor tardó demasiado en responder (tiempo de espera agotado).")
        except requests.exceptions.RequestException as exc:
            self._emit(method, service, path, 0, started, "error de red")
            raise ApiError(f"Error de red: {exc}")
        finally:
            session_store.save_cookies(self.session.cookies)

        self.last_headers = response.headers
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        note = "Idempotent-Replay" if response.headers.get("Idempotent-Replay") == "true" else ""
        self._emit(method, service, path, response.status_code, started, note)

        if response.status_code == 401 and auth and send_headers.get("Authorization") and _retry and service != "auth":
            # Token vencido/revocado a medias: una sola renovación y se reintenta (si no se puede, se informa el 401).
            if self._try_refresh():
                return self._request(method, service, path, json_body, params, headers, auth, _retry=False)

        if not response.ok and not data and "text/html" in response.headers.get("Content-Type", ""):
            # El microservicio SIEMPRE responde JSON: una página HTML con 403/407/5xx viene de un firewall o proxy de la red.
            raise ApiError("Una red o firewall bloqueó la conexión con el servidor (página de filtro web, HTTP "
                           f"{response.status_code}). No es un problema de tu usuario ni de tu contraseña: "
                           "cambia de red (por ejemplo, datos del celular) e intenta de nuevo.",
                           response.status_code, "network_blocked")
        if not response.ok:
            raise ApiError(self._mensaje_error(data, response.status_code), response.status_code, self._codigo_error(data))
        return data

    @staticmethod
    def _mensaje_error(data, status):
        # Todos los servicios usan {"error": {"code":.., "message":.., "details":[{"field":..,"message":..}]}};
        # books también puede responder {"error": "texto"}
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            base = error.get("message") or f"El servidor respondió con un error (HTTP {status})."
            detalles = error.get("details")
            if detalles:
                extra = "; ".join(f"{d.get('field')}: {d.get('message')}" if d.get("field") else d.get("message", "")
                                  for d in detalles if d.get("message"))
                if extra:
                    return f"{base}: {extra}"
            return base
        if isinstance(error, str):
            return error
        return f"El servidor respondió con un error (HTTP {status})."

    @staticmethod
    def _codigo_error(data):
        error = data.get("error") if isinstance(data, dict) else None
        return error.get("code") if isinstance(error, dict) else None

    @staticmethod
    def _only_filled(campos):
        return {k: v for k, v in campos.items() if v not in (None, "")}

    # --------------------------------------------------------- auth (login)
    def register(self, nombre, apellido_paterno, apellido_materno, email, password):
        return self._request("POST", "auth", "/register", {
            "nombre": nombre, "apellido_paterno": apellido_paterno,
            "apellido_materno": apellido_materno, "email": email, "password": password,
        }, auth=False)

    def login(self, email, password):
        data = self._request("POST", "auth", "/login", {"email": email, "password": password}, auth=False)
        session_store.save(data["user"]["email"])
        self._set_tokens(data)
        return data

    def logout(self):
        try:
            self._request("POST", "auth", "/logout")
        finally:
            session_store.clear()
            self._clear_tokens()

    def get_session(self):
        """GET /session: revalida contra el servidor. Lanza ApiError(status=401)
        si no hay sesión válida (caducada o inexistente) -- la GUI decide
        entonces regresar a la pantalla de login (punto 3 del enunciado)."""
        return self._request("GET", "auth", "/session")

    def extend_session(self):
        return self._request("POST", "auth", "/session/extend")

    def update_profile(self, **campos):
        """PATCH /profile: solo se envían los campos con valor (no vacíos)."""
        payload = self._only_filled(campos)
        return self._request("PATCH", "auth", "/profile", payload) if payload else None

    # ------------------------------------------------------------- books
    def list_books(self):
        return self._request("GET", "books", "/books").get("books", [])

    def get_book(self, isbn):
        return self._request("GET", "books", f"/books/{isbn}")

    def list_images(self):
        return self._request("GET", "books", "/books/images").get("books", [])

    def list_concepts(self):
        return self._request("GET", "books", "/concepts").get("concepts", [])

    def create_book(self, **campos):
        return self._request("POST", "books", "/books", campos)

    def replace_book(self, isbn, **campos):
        """PUT: reemplazo COMPLETO -- todos los campos son obligatorios."""
        return self._request("PUT", "books", f"/books/{isbn}", campos)

    def patch_book(self, isbn, **campos):
        """PATCH: actualización PARCIAL -- solo se envían los campos con valor."""
        return self._request("PATCH", "books", f"/books/{isbn}", self._only_filled(campos))

    def delete_book(self, isbn):
        return self._request("DELETE", "books", f"/books/{isbn}")

    # ------------------------------------------------------------- users
    def list_roles(self):
        return self._request("GET", "users", "/roles").get("roles", [])

    def list_users(self, limit=100, offset=0):
        return self._request("GET", "users", "/users", params={"limit": limit, "offset": offset}).get("users", [])

    def my_user(self):
        return self._request("GET", "users", "/users/me")["user"]

    def get_user(self, user_id):
        return self._request("GET", "users", f"/users/{user_id}")["user"]

    def create_user(self, **campos):
        return self._request("POST", "users", "/users", campos)

    def replace_user(self, user_id, **campos):
        """PUT: todos los campos (email, display_name, nombre, apellidos, role_id, is_active)."""
        return self._request("PUT", "users", f"/users/{user_id}", campos)

    def patch_user(self, user_id, **campos):
        return self._request("PATCH", "users", f"/users/{user_id}", campos)

    def set_user_password(self, user_id, password, current_password=None):
        body = {"password": password}
        if current_password:
            body["current_password"] = current_password
        return self._request("PUT", "users", f"/users/{user_id}/password", body)

    def delete_user(self, user_id):
        return self._request("DELETE", "users", f"/users/{user_id}")

    # ----------------------------------------------------------- authors
    def list_authors(self, limit=100):
        return self._request("GET", "authors", "/authors", params={"limit": limit}).get("authors", [])

    def get_author(self, author_id):
        return self._request("GET", "authors", f"/authors/{author_id}")["author"]

    def author_books(self, author_id):
        return self._request("GET", "authors", f"/authors/{author_id}/books").get("books", [])

    def create_author(self, **campos):
        return self._request("POST", "authors", "/authors", campos)

    def replace_author(self, author_id, **campos):
        return self._request("PUT", "authors", f"/authors/{author_id}", campos)

    def patch_author(self, author_id, **campos):
        return self._request("PATCH", "authors", f"/authors/{author_id}", self._only_filled(campos))

    def delete_author(self, author_id):
        return self._request("DELETE", "authors", f"/authors/{author_id}")

    def link_author_book(self, author_id, isbn, author_order=None):
        body = {"isbn": isbn}
        if author_order is not None:
            body["author_order"] = author_order
        return self._request("POST", "authors", f"/authors/{author_id}/books", body)

    def unlink_author_book(self, author_id, isbn):
        return self._request("DELETE", "authors", f"/authors/{author_id}/books/{isbn}")

    # ----------------------------------------------------------- pedidos
    def list_orders(self, status=None, user_id=None, limit=100):
        params = self._only_filled({"status": status, "user_id": user_id, "limit": limit})
        return self._request("GET", "pedidos", "/pedidos", params=params).get("orders", [])

    def get_order(self, order_id):
        return self._request("GET", "pedidos", f"/pedidos/{order_id}")["order"]

    def create_order(self, items, user_id=None):
        body = {"items": items}
        if user_id:
            body["user_id"] = user_id
        return self._request("POST", "pedidos", "/pedidos", body)

    def change_order_status(self, order_id, status):
        return self._request("PATCH", "pedidos", f"/pedidos/{order_id}/status", {"status": status})

    def cancel_order(self, order_id):
        return self._request("DELETE", "pedidos", f"/pedidos/{order_id}")

    # ------------------------------------------------------------- pagos
    def list_payments(self, order_id=None, limit=100):
        params = self._only_filled({"order_id": order_id, "limit": limit})
        return self._request("GET", "pagos", "/pagos", params=params).get("payments", [])

    def get_payment(self, payment_id):
        return self._request("GET", "pagos", f"/pagos/{payment_id}")["payment"]

    def create_payment(self, order_id, method, amount, idempotency_key):
        """POST /pagos con la cabecera Idempotency-Key. Tras la llamada, `last_headers['Idempotent-Replay']`
        vale 'true' si el servidor devolvió el pago original en vez de cobrar otra vez."""
        return self._request("POST", "pagos", "/pagos", {"order_id": order_id, "method": method, "amount": amount},
                             headers={"Idempotency-Key": idempotency_key})

    def modify_payment(self, payment_id, verb="PUT"):
        """Los pagos son inmutables: el servidor responde 405 (se usa para demostrarlo)."""
        return self._request(verb, "pagos", f"/pagos/{payment_id}", {"status": "x"})

    # ---------------------------------------------------------- semáforo
    def health(self, base_url):
        """Devuelve ('green'|'yellow'|'red', mensaje, redis) con redis = 'ok'|'unavailable'|None.
        No lanza ApiError: el semáforo necesita el resultado SIEMPRE, incluso si el servicio está caído.

          verde    -> 200: el servicio, PostgreSQL y Redis responden.
          amarillo -> el servicio responde pero algo de lo que depende no (Redis o PostgreSQL): degradado.
          rojo     -> el servicio no responde."""
        try:
            response = requests.get(f"{base_url}/health", params={"format": "json"}, timeout=4)
        except requests.exceptions.RequestException:
            return "red", "Sin respuesta del servidor", None
        try:
            data = response.json()
        except ValueError:
            data = {}
        error = data.get("error") if isinstance(data, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if response.status_code == 200 and data.get("status") == "ok":
            redis = data.get("redis")
            if redis in (None, "ok"):
                return "green", "Activo: PostgreSQL" + (" y Redis OK" if redis else " OK"), redis
            return ("yellow", "Activo, pero Redis no responde: lecturas públicas sí; sesión, escrituras y pagos darán 503",
                    "unavailable")
        if code == "redis_unavailable":
            return "yellow", "Activo, pero Redis no responde: no hay login ni operaciones protegidas (503)", "unavailable"
        if response.status_code in (503, 500):
            return "yellow", self._mensaje_error(data, response.status_code), None
        return "yellow", f"Respuesta inesperada (HTTP {response.status_code})", None
