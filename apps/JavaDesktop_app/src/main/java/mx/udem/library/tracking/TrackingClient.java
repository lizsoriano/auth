package mx.udem.library.tracking;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.Json;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.time.Duration;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

/**
 * Cliente WebSocket del rastreo (JDK {@code java.net.http.WebSocket}), integrado en la aplicación Java.
 *
 * <p>Protocolo con el servidor ({@code /ws/tracking}):
 * <ol>
 *   <li>al abrir se envía {@code {"type":"auth","token":"<JWT>","code":"LIB-MTY-…"}} (el token NO va en la URL);</li>
 *   <li>el servidor valida el JWT y confirma con el servicio Pedidos que el pedido es del usuario; si no, responde
 *       {@code {"type":"error",…}} y cierra;</li>
 *   <li>llega un {@code snapshot} (con la ruta completa) y luego un {@code update} por segundo hasta «entregado»;</li>
 *   <li>cuando la sesión renueva el JWT se manda {@code {"type":"refresh","token":…}}; cada 20 s va un {@code ping}.</li>
 * </ol>
 * Si la conexión se cae sin motivo fatal se reintenta con espera creciente (máx. 5 veces).
 */
public final class TrackingClient {

    public interface Listener {
        void onState(State state);

        /** Mensaje del servidor ({@code snapshot}, {@code update}, {@code pong}, {@code token_refreshed}). */
        void onMessage(JsonNode message);

        /** Error del servidor o de conexión; {@code fatal} = no se reintentará. */
        void onError(String code, String message, boolean fatal);
    }

    public enum State { CONNECTING, CONNECTED, RECONNECTING, CLOSED }

    /** Errores que no se arreglan reintentando: el usuario debe corregir algo (o no es su pedido). */
    private static final Set<String> FATAL = Set.of("order_not_found", "order_not_paid", "order_cancelled", "invalid_code",
            "token_invalid", "token_missing", "tracking_disabled", "forbidden", "orders_unavailable");
    private static final int MAX_RETRIES = 5;

    private final String wsUrl;
    private final Supplier<String> token;
    private final Listener listener;
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(6)).build();
    private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "tracking-timer");
        t.setDaemon(true);
        return t;
    });

    private volatile WebSocket socket;
    private volatile String code;
    private volatile boolean userClosed;
    private volatile boolean delivered;
    private volatile int attempts;

    public TrackingClient(String wsUrl, Supplier<String> token, Listener listener) {
        this.wsUrl = wsUrl;
        this.token = token;
        this.listener = listener;
        timer.scheduleWithFixedDelay(this::ping, 20, 20, TimeUnit.SECONDS);
    }

    public void connect(String trackingCode) {
        this.code = trackingCode;
        this.userClosed = false;
        this.delivered = false;
        this.attempts = 0;
        open(State.CONNECTING);
    }

    /** Reenvía al servidor el JWT recién renovado para que no cierre la conexión al vencer el anterior. */
    public void refreshToken(String newToken) {
        send(Json.write(Map.of("type", "refresh", "token", newToken)));
    }

    public void close() {
        userClosed = true;
        WebSocket ws = socket;
        socket = null;
        if (ws != null) {
            ws.sendClose(WebSocket.NORMAL_CLOSURE, "cliente cerró").exceptionally(e -> null);
        }
        listener.onState(State.CLOSED);
    }

    public void shutdown() {
        close();
        timer.shutdownNow();
    }

    private void open(State state) {
        listener.onState(state);
        client.newWebSocketBuilder().connectTimeout(Duration.ofSeconds(6)).buildAsync(URI.create(wsUrl), new Handler())
                .whenComplete((ws, error) -> {
                    if (error != null) {
                        failed("network", "No se pudo conectar con el servidor de rastreo.");
                    }
                });
    }

    private void send(String text) {
        WebSocket ws = socket;
        if (ws != null) {
            ws.sendText(text, true).exceptionally(e -> null);
        }
    }

    private void ping() {
        send("{\"type\":\"ping\"}");
    }

    private void failed(String errorCode, String message) {
        if (userClosed) {
            return;
        }
        boolean fatal = FATAL.contains(errorCode) || delivered;
        if (fatal || attempts >= MAX_RETRIES) {
            listener.onError(errorCode, message, true);
            listener.onState(State.CLOSED);
            return;
        }
        attempts++;
        listener.onError(errorCode, message + " Reintentando (" + attempts + "/" + MAX_RETRIES + ")…", false);
        timer.schedule(() -> {
            if (!userClosed) {
                open(State.RECONNECTING);
            }
        }, 2L * attempts, TimeUnit.SECONDS);
    }

    private final class Handler implements WebSocket.Listener {

        private final StringBuilder buffer = new StringBuilder();

        @Override
        public void onOpen(WebSocket ws) {
            socket = ws;
            ws.sendText(Json.write(Map.of("type", "auth", "token", token.get(), "code", code)), true);
            ws.request(1);
        }

        @Override
        public CompletionStage<?> onText(WebSocket ws, CharSequence data, boolean last) {
            buffer.append(data);
            if (last) {
                String text = buffer.toString();
                buffer.setLength(0);
                handle(text);
            }
            ws.request(1);
            return null;
        }

        private void handle(String text) {
            JsonNode message;
            try {
                message = Json.parse(text);
            } catch (IllegalArgumentException e) {
                return;
            }
            String type = message.path("type").asText();
            if ("error".equals(type)) {
                failed(message.path("code").asText("error"), message.path("message").asText("Error del servidor de rastreo."));
                return;
            }
            if ("snapshot".equals(type) || "update".equals(type)) {
                if (attempts > 0 || !userClosed) {
                    attempts = 0;
                }
                if (message.path("delivered").asBoolean()) {
                    delivered = true;
                }
                if ("snapshot".equals(type)) {
                    listener.onState(State.CONNECTED);
                }
            }
            listener.onMessage(message);
        }

        @Override
        public CompletionStage<?> onClose(WebSocket ws, int statusCode, String reason) {
            if (socket == ws) {
                socket = null;
            }
            if (!userClosed && !delivered && statusCode != 1008) {
                failed("closed", "Se perdió la conexión con el servidor de rastreo.");
            } else if (!userClosed) {
                listener.onState(State.CLOSED);
            }
            return null;
        }

        @Override
        public void onError(WebSocket ws, Throwable error) {
            if (socket == ws) {
                socket = null;
            }
            failed("network", "Error de red en el rastreo.");
        }
    }
}
