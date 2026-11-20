package mx.udem.library.model;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.Json;

import java.math.BigDecimal;

/** Pago simulado registrado en el servicio Pagos (no hay datos bancarios: solo método y monto). */
public record Payment(long id, long orderId, BigDecimal amount, String method, String status, String createdAt) {

    public static Payment from(JsonNode n) {
        return new Payment(n.path("payment_id").asLong(), n.path("order_id").asLong(), Json.money(n.get("amount")),
                Json.text(n, "method"), Json.text(n, "status"), Json.text(n, "created_at"));
    }
}
