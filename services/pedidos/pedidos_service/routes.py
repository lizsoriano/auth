"""Rutas de Pedidos (todas exigen JWT; no hay lecturas públicas porque los pedidos son datos privados).

  customer       -> crea, ve y cancela SOLO sus pedidos (lo ajeno responde 404, no revela que existe).
  staff y admin  -> ven y gestionan todos; pueden crear a nombre de otro usuario (user_id) y marcar «enviado».
401 sin token/inválido/revocado · 403 rol insuficiente · 503 si Redis no responde (no se puede verificar el token).

Estados: pendiente(1) -> cancelado(4) [repone stock] · pagado(2) -> enviado(3). «pagado» solo lo marca el servicio Pagos.
Cambiar de estado toma el candado lock:order:<id> en Redis (el mismo que usa Pagos): dos operaciones sobre el mismo
pedido no se pisan, aunque vengan de servicios distintos.
"""
from flask import current_app, request
from library_common import ApiError, LockNotAcquired, invalidate_all_books
from library_common.serializers import render
from library_common.service_kit import claims, is_privileged, json_body, page_args

STATUS_IDS = {"pendiente": 1, "pagado": 2, "enviado": 3, "cancelado": 4}
MAX_ITEMS = 100
MAX_QUANTITY = 999999
LOCK_SECONDS = 10


def _redis():
    return current_app.extensions["redis"]


def _actor():
    """None = administrador/staff (sin restricción de dueño); un id = cliente (solo lo suyo)."""
    c = claims()
    return None if is_privileged(c) else c["user_id"]


def _clean_items(items):
    if not isinstance(items, list) or not items:
        raise ApiError("validation_error", "items debe ser una lista con al menos una línea", 400,
                       [{"field": "items", "message": "Lista no vacía de {isbn, quantity}"}])
    if len(items) > MAX_ITEMS:
        raise ApiError("validation_error", f"Un pedido admite como máximo {MAX_ITEMS} líneas", 400)
    clean, problems = [], []
    for i, line in enumerate(items):
        isbn = line.get("isbn") if isinstance(line, dict) else None
        qty = line.get("quantity") if isinstance(line, dict) else None
        if not isinstance(isbn, str) or not isbn.strip() or len(isbn.strip()) > 17:
            problems.append({"field": f"items[{i}].isbn", "message": "isbn obligatorio (texto de hasta 17 caracteres)"})
        elif isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= MAX_QUANTITY:
            problems.append({"field": f"items[{i}].quantity", "message": f"quantity debe ser un entero entre 1 y {MAX_QUANTITY}"})
        else:
            clean.append({"isbn": isbn.strip(), "quantity": qty})
    if problems:
        raise ApiError("validation_error", "Los datos enviados no son válidos", 400, problems)
    return clean


def register_routes(app, jwt_auth, repo):
    any_user = jwt_auth.required()

    @app.post("/pedidos")
    @any_user
    def create_order():
        data = json_body()
        c = claims()
        user_id = data.get("user_id", c["user_id"])
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ApiError("validation_error", "user_id debe ser un entero positivo", 400)
        if user_id != c["user_id"] and not is_privileged(c):
            raise ApiError("forbidden", "Solo staff o admin pueden crear pedidos a nombre de otro usuario.", 403)
        order = repo.create(user_id, _clean_items(data.get("items")))
        invalidate_all_books(_redis())  # el stock cambió: books:* ya no es válido
        return render({"message": "Pedido creado. Quedó pendiente de pago.", "order": order}, 201)

    @app.get("/pedidos")
    @any_user
    def list_orders():
        limit, offset = page_args()
        c = claims()
        user_id = c["user_id"] if not is_privileged(c) else None
        if is_privileged(c) and "user_id" in request.args:
            try:
                user_id = int(request.args["user_id"])
            except ValueError:
                raise ApiError("validation_error", "user_id debe ser un entero", 400)
        status = request.args.get("status")
        if status is not None and status not in STATUS_IDS:
            raise ApiError("validation_error", f"status debe ser uno de: {', '.join(STATUS_IDS)}", 400)
        orders = repo.list(user_id, STATUS_IDS.get(status), limit, offset)
        return render({"orders": orders, "limit": limit, "offset": offset})

    @app.get("/pedidos/<int:order_id>")
    @any_user
    def get_order(order_id):
        return render({"order": repo.get(order_id, _actor())})

    def change_status(order_id, new_status):
        if new_status == "pagado":
            raise ApiError("invalid_transition",
                           "Un pedido pasa a «pagado» registrando su pago en el servicio Pagos (POST /pagos).", 409)
        if new_status not in ("cancelado", "enviado"):
            raise ApiError("validation_error", "status debe ser «cancelado» o «enviado»", 400)
        if new_status == "enviado" and not is_privileged():
            raise ApiError("forbidden", "Solo staff o admin pueden marcar un pedido como enviado.", 403)
        try:
            with _redis().lock(f"order:{order_id}", LOCK_SECONDS):
                order = repo.change_status(order_id, STATUS_IDS[new_status], _actor())
        except LockNotAcquired:
            raise ApiError("order_busy", "Otra operación está modificando este pedido. Intenta de nuevo.", 409)
        if new_status == "cancelado":
            invalidate_all_books(_redis())  # cancelar repone stock
        return render({"message": f"Pedido {new_status}.", "order": order})

    @app.patch("/pedidos/<int:order_id>/status")
    @any_user
    def patch_status(order_id):
        return change_status(order_id, json_body().get("status"))

    @app.delete("/pedidos/<int:order_id>")
    @any_user
    def delete_order(order_id):
        return change_status(order_id, "cancelado")  # cancelar = el «borrado» de un pedido (se conserva el historial)
