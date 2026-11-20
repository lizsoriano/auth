package mx.udem.library.model;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.Json;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/** Pedido tal como lo devuelve el servicio Pedidos (estados: pendiente, pagado, enviado, cancelado). */
public record Order(long id, long userId, String status, BigDecimal total, String createdAt, List<Item> items) {

    public record Item(String isbn, String title, int quantity, BigDecimal unitPrice) {
        public BigDecimal subtotal() {
            return unitPrice.multiply(BigDecimal.valueOf(quantity));
        }
    }

    public static Order from(JsonNode n) {
        List<Item> items = new ArrayList<>();
        for (JsonNode i : n.path("items")) {
            items.add(new Item(Json.text(i, "isbn"), Json.text(i, "title"), i.path("quantity").asInt(),
                    Json.money(i.get("unit_price"))));
        }
        return new Order(n.path("order_id").asLong(), n.path("user_id").asLong(), Json.text(n, "status"),
                Json.money(n.get("total")), Json.text(n, "created_at"), items);
    }

    public boolean pending() {
        return "pendiente".equals(status);
    }

    /** Solo se rastrean pedidos ya pagados (lo mismo que exige el servidor de rastreo). */
    public boolean trackable() {
        return "pagado".equals(status) || "enviado".equals(status);
    }

    public int units() {
        return items.stream().mapToInt(Item::quantity).sum();
    }

    /** Código de rastreo del pedido (mismo formato que genera el servidor: LIB-MTY-&lt;año&gt;-&lt;id a 6 dígitos&gt;). */
    public String trackingCode() {
        return TrackingCode.forOrder(this);
    }
}
