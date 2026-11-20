package mx.udem.library.api;

import mx.udem.library.api.HttpApi.Service;
import mx.udem.library.model.Payment;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Microservicio Pagos. El pago es SIMULADO: solo se manda el pedido, el método (tarjeta, transferencia o efectivo) y
 * el monto exacto; nunca datos bancarios. La cabecera {@code Idempotency-Key} evita cobrar dos veces si se reintenta.
 */
public final class PaymentsApi {

    public static final List<String> METHODS = List.of("tarjeta", "transferencia", "efectivo");

    private final HttpApi http;

    public PaymentsApi(HttpApi http) {
        this.http = http;
    }

    public Payment pay(long orderId, String method, BigDecimal amount, String idempotencyKey) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("order_id", orderId);
        body.put("method", method);
        body.put("amount", amount);
        HttpApi.Response r = http.call(Service.PAGOS, "POST", "/pagos", null, body, Map.of("Idempotency-Key", idempotencyKey), true);
        return Payment.from(r.body().path("payment"));
    }

    public List<Payment> ofOrder(long orderId) {
        List<Payment> payments = new ArrayList<>();
        http.get(Service.PAGOS, "/pagos", Map.of("order_id", String.valueOf(orderId))).path("payments")
                .forEach(p -> payments.add(Payment.from(p)));
        return payments;
    }
}
