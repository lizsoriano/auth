package mx.udem.library.api;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.model.User;

import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Consumer;

/**
 * Sesión del usuario: el JWT de acceso (20 min), el refresh token (un solo uso) y el usuario autenticado.
 * Todo vive SOLO en memoria: nunca se escribe a disco ni se registra en bitácoras.
 */
public final class Session {

    private volatile String accessToken;
    private volatile String refreshToken;
    private volatile long deadlineNanos;
    private volatile User user;
    private final List<Consumer<String>> tokenListeners = new CopyOnWriteArrayList<>();

    /** Guarda los tokens de la respuesta de {@code POST /login} o {@code POST /token/refresh}. */
    public void setTokens(JsonNode data) {
        accessToken = data.path("token").asText(null);
        refreshToken = data.path("refresh_token").asText(null);
        long seconds = data.path("token_expires_in_seconds").asLong(1200);
        deadlineNanos = System.nanoTime() + seconds * 1_000_000_000L;
        String token = accessToken;
        if (token != null) {
            tokenListeners.forEach(l -> l.accept(token));
        }
    }

    public void user(User user) {
        this.user = user;
    }

    public User user() {
        return user;
    }

    public String accessToken() {
        return accessToken;
    }

    public String refreshToken() {
        return refreshToken;
    }

    public boolean active() {
        return accessToken != null;
    }

    /** Segundos de vida que le quedan al JWT según el reloj local (no depende del reloj del servidor). */
    public long secondsLeft() {
        return accessToken == null ? 0 : Math.max(0, (deadlineNanos - System.nanoTime()) / 1_000_000_000L);
    }

    public void clear() {
        accessToken = null;
        refreshToken = null;
        user = null;
        deadlineNanos = 0;
    }

    /** Avisa cada vez que hay un JWT nuevo (el rastreo por WebSocket lo reenvía al servidor). */
    public void onNewToken(Consumer<String> listener) {
        tokenListeners.add(listener);
    }

    /** Claims del JWT solo para MOSTRARLOS; la firma la valida cada servicio. */
    public JsonNode claims() {
        String token = accessToken;
        if (token == null) {
            return Json.MAPPER.createObjectNode();
        }
        try {
            String[] parts = token.split("\\.");
            return Json.parse(new String(Base64.getUrlDecoder().decode(parts[1]), StandardCharsets.UTF_8));
        } catch (RuntimeException e) {
            return Json.MAPPER.createObjectNode();
        }
    }
}
