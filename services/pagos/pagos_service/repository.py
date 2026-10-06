"""Acceso a datos de Pagos: SOLO funciones SQL (fn_pago*, migración 010). fn_pagos_registrar inserta el pago y pasa el
pedido a «pagado» en UNA transacción; pagos_service_user no puede leer ni escribir tablas."""

PAYMENT_ERRORS = {
    "PG001": (404, "not_found", None),
    "PG002": (409, "order_not_payable", None),
    "PG003": (409, "amount_mismatch", None),
    "PG004": (409, "idempotency_key_reused", None),
    "PG005": (400, "validation_error", None),
    "PG006": (404, "not_found", None),
}


class PaymentsRepository:
    def __init__(self, pg):
        self.pg = pg

    def ping(self):
        self.pg.ping()

    def register(self, order_id, actor_user_id, privileged, method, amount, idempotency_key):
        """`amount` llega como texto decimal exacto («219.00»): nunca pasa por float."""
        return self.pg.one("SELECT fn_pagos_registrar(%s, %s, %s, %s, %s::numeric, %s) AS p",
                           (order_id, actor_user_id, privileged, method, amount, idempotency_key))["p"]

    def list(self, user_id, order_id, limit, offset):
        return self.pg.query("SELECT * FROM fn_pagos_listar(%s, %s, %s, %s)", (user_id, order_id, limit, offset))

    def get(self, payment_id, actor_user_id):
        return self.pg.one("SELECT fn_pago_obtener(%s, %s) AS p", (payment_id, actor_user_id))["p"]
