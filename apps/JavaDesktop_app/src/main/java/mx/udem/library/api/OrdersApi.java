package mx.udem.library.api;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.HttpApi.Service;
import mx.udem.library.model.CartLine;
import mx.udem.library.model.Order;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Microservicio Pedidos (todo exige JWT): un cliente ve solo lo suyo; staff y admin ven todo. */
public final class OrdersApi {

    private final HttpApi http;

    public OrdersApi(HttpApi http) {
        this.http = http;
    }

    /** {@code POST /pedidos {items:[{isbn, quantity}]}}: baja el stock y deja el pedido «pendiente» de pago. */
    public Order create(List<CartLine> lines) {
        List<Map<String, Object>> items = new ArrayList<>();
        for (CartLine line : lines) {
            items.add(Map.of("isbn", line.book().isbn(), "quantity", line.quantity()));
        }
        return Order.from(http.post(Service.PEDIDOS, "/pedidos", Map.of("items", items)).path("order"));
    }

    public List<Order> list(int limit) {
        List<Order> orders = new ArrayList<>();
        JsonNode data = http.get(Service.PEDIDOS, "/pedidos", Map.of("limit", String.valueOf(limit)));
        data.path("orders").forEach(o -> orders.add(Order.from(o)));
        return orders;
    }

    public Order get(long id) {
        return Order.from(http.get(Service.PEDIDOS, "/pedidos/" + id).path("order"));
    }

    /** {@code DELETE /pedidos/{id}}: cancelar repone el stock; solo si aún está pendiente. */
    public Order cancel(long id) {
        return Order.from(http.delete(Service.PEDIDOS, "/pedidos/" + id).path("order"));
    }
}
