"""Acceso a datos de Pedidos: SOLO funciones SQL (fn_pedido*, migración 009). El rol pedidos_service_user no puede
leer ni escribir tablas; el stock de books solo cambia dentro de fn_pedidos_crear / fn_pedido_cambiar_estado."""
import json

ORDER_ERRORS = {
    "PD001": (400, "validation_error", None),
    "PD002": (409, "insufficient_stock", None),
    "PD003": (404, "not_found", None),
    "PD004": (409, "invalid_transition", None),
    "PD005": (404, "book_not_found", None),
    "PD007": (400, "invalid_user", None),
}


class OrdersRepository:
    def __init__(self, pg):
        self.pg = pg

    def ping(self):
        self.pg.ping()

    def create(self, user_id, items):
        return self.pg.one("SELECT fn_pedidos_crear(%s, %s::jsonb) AS o", (user_id, json.dumps(items)))["o"]

    def list(self, user_id, status_id, limit, offset):
        return self.pg.query("SELECT * FROM fn_pedidos_listar(%s, %s::smallint, %s, %s)",
                             (user_id, status_id, limit, offset))

    def get(self, order_id, actor_user_id):
        """actor_user_id None = admin/staff (cualquier pedido); un id = solo si el pedido es de ese usuario."""
        return self.pg.one("SELECT fn_pedido_obtener(%s, %s) AS o", (order_id, actor_user_id))["o"]

    def change_status(self, order_id, status_id, actor_user_id):
        return self.pg.one("SELECT fn_pedido_cambiar_estado(%s, %s::smallint, %s) AS o",
                           (order_id, status_id, actor_user_id))["o"]
