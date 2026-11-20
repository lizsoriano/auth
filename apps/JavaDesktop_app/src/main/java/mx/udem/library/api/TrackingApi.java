package mx.udem.library.api;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.HttpApi.Service;

import java.util.Map;

/**
 * Servidor de rastreo (Flask + Flask-Sock). Parte REST: iniciar o recuperar el seguimiento de un pedido y consultar su
 * estado actual por código. La posición en tiempo real llega por WebSocket (ver {@code TrackingClient}).
 * Ambas partes exigen el mismo JWT y el servidor confirma con el servicio Pedidos que el pedido sea del usuario.
 */
public final class TrackingApi {

    private final HttpApi http;

    public TrackingApi(HttpApi http) {
        this.http = http;
    }

    /** {@code POST /tracking {order_id}}: solo pedidos pagados. Devuelve el objeto {@code tracking} (código, estado, ruta…). */
    public JsonNode open(long orderId) {
        return http.post(Service.TRACKING, "/tracking", Map.of("order_id", orderId)).path("tracking");
    }

    /** {@code GET /tracking/<código>}: vuelve a consultar el seguimiento con solo el código. */
    public JsonNode byCode(String code) {
        return http.get(Service.TRACKING, "/tracking/" + code, Map.of("route", "1")).path("tracking");
    }
}
