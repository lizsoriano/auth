"""Rutas de Pagos (todas exigen JWT).

  POST /pagos   Cabecera obligatoria `Idempotency-Key`. customer paga SOLO sus pedidos; staff/admin pagan cualquiera.
                Registra el pago y pasa el pedido a «pagado» en una sola transacción (fn_pagos_registrar).
  GET  /pagos, /pagos/<id>   customer ve solo los pagos de sus pedidos; staff/admin ven todos.
  PUT/PATCH/DELETE /pagos/<id>   Los pagos son inmutables: con JWT responden 405, sin JWT 401.

Idempotencia en DOS capas: Redis (`payment:idem:<usuario>:<clave>`, 24 h) devuelve la respuesta original sin tocar la
base ni cobrar de nuevo, y la base (`payments.idempotency_key` UNIQUE) lo garantiza aunque Redis pierda la clave.
Sin Redis NO se cobra (503): no se puede garantizar que un reintento no duplique el pago.
Una clave reutilizada con otro pedido, método o monto es 409 (nunca se devuelve el pago de otra petición).
"""
import hashlib
import re
from decimal import Decimal, InvalidOperation

from flask import current_app, request
from library_common import ApiError, LockNotAcquired
from library_common.serializers import render
from library_common.service_kit import claims, is_privileged, json_body, page_args

IDEM_NAMESPACE = "payment:idem"
IDEM_DONE_TTL = 24 * 3600
IDEM_PENDING_TTL = 60  # corto: si el servicio muere a medias, el cliente puede reintentar con la misma clave
LOCK_SECONDS = 10
KEY_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}")
METHODS = ("tarjeta", "transferencia", "efectivo")


def _redis():
    return current_app.extensions["redis"]


def _amount(value):
    """Monto como texto decimal exacto con a lo más 2 decimales; acepta número JSON o texto numérico."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ApiError("validation_error", "amount debe ser un número positivo con a lo más 2 decimales", 400)
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise ApiError("validation_error", "amount debe ser un número positivo con a lo más 2 decimales", 400)
    if not d.is_finite() or d <= 0 or d.as_tuple().exponent < -2 or d >= Decimal("10000000000"):
        raise ApiError("validation_error", "amount debe ser un número positivo con a lo más 2 decimales", 400)
    return f"{d:.2f}"


def _release_quietly(scoped_key):
    try:
        _redis().idem_release(IDEM_NAMESPACE, scoped_key)
    except Exception:  # noqa: BLE001 - lo importante es reportar el error original, no este
        current_app.logger.warning("No se pudo liberar la reserva de idempotencia")


def register_routes(app, jwt_auth, repo):
    any_user = jwt_auth.required()

    @app.post("/pagos")
    @any_user
    def create_payment():
        c = claims()
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            raise ApiError("idempotency_key_required",
                           "Envía la cabecera Idempotency-Key (un valor único por intento de pago): evita cobrar dos veces "
                           "si reintentas.", 400)
        if not KEY_RE.fullmatch(key):
            raise ApiError("validation_error", "Idempotency-Key admite 1 a 64 caracteres: letras, números y . _ : -", 400)
        data, problems = json_body(), []
        order_id, method = data.get("order_id"), data.get("method")
        if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id < 1:
            problems.append({"field": "order_id", "message": "order_id debe ser un entero positivo"})
        if method not in METHODS:
            problems.append({"field": "method", "message": f"method debe ser uno de: {', '.join(METHODS)}"})
        if problems:
            raise ApiError("validation_error", "Los datos enviados no son válidos", 400, problems)
        amount = _amount(data.get("amount"))

        fingerprint = hashlib.sha256(f"{order_id}|{method}|{amount}".encode()).hexdigest()
        scoped = f"{c['user_id']}:{key}"  # la clave es por usuario: dos usuarios pueden usar la misma sin chocar
        redis = _redis()

        if not redis.idem_claim(IDEM_NAMESPACE, scoped, IDEM_PENDING_TTL):  # RedisUnavailable -> 503, no se cobra
            state = redis.idem_get(IDEM_NAMESPACE, scoped)
            if state and state.get("state") == "done":
                stored = state["result"]
                if stored["fingerprint"] != fingerprint:
                    raise ApiError("idempotency_key_reused",
                                   "Esa Idempotency-Key ya se usó con otro pedido, método o monto.", 409)
                response = render(stored["payload"], 200)
                response.headers["Idempotent-Replay"] = "true"
                return response
            raise ApiError("request_in_progress", "Esa Idempotency-Key ya se está procesando. Espera y reintenta.", 409)

        try:
            with redis.lock(f"order:{order_id}", LOCK_SECONDS):  # el mismo candado que usa Pedidos
                payment = repo.register(order_id, c["user_id"], is_privileged(c), method, amount, scoped)
        except LockNotAcquired:
            _release_quietly(scoped)
            raise ApiError("order_busy", "Otra operación está modificando este pedido. Intenta de nuevo.", 409)
        except BaseException:
            _release_quietly(scoped)  # el intento falló: la clave queda libre para reintentar
            raise

        duplicated = bool(payment.pop("duplicated", False))
        payload = {"message": "Pago ya registrado con esa clave." if duplicated else "Pago registrado. El pedido quedó pagado.",
                   "payment": payment}
        redis.idem_complete(IDEM_NAMESPACE, scoped, {"fingerprint": fingerprint, "payload": payload}, IDEM_DONE_TTL)
        return render(payload, 200 if duplicated else 201)

    @app.get("/pagos")
    @any_user
    def list_payments():
        limit, offset = page_args()
        c = claims()
        user_id = None if is_privileged(c) else c["user_id"]
        order_id = request.args.get("order_id")
        if order_id is not None:
            try:
                order_id = int(order_id)
            except ValueError:
                raise ApiError("validation_error", "order_id debe ser un entero", 400)
        return render({"payments": repo.list(user_id, order_id, limit, offset), "limit": limit, "offset": offset})

    @app.get("/pagos/<int:payment_id>")
    @any_user
    def get_payment(payment_id):
        c = claims()
        return render({"payment": repo.get(payment_id, None if is_privileged(c) else c["user_id"])})

    @app.route("/pagos/<int:payment_id>", methods=["PUT", "PATCH", "DELETE"])
    @any_user
    def immutable(payment_id):
        raise ApiError("payments_are_immutable",
                       "Los pagos no se modifican ni se eliminan: registra el movimiento correspondiente.", 405)
