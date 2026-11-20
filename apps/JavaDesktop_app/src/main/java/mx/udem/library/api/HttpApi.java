package mx.udem.library.api;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.config.ServiceUrls;

import java.io.IOException;
import java.net.CookieManager;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpHeaders;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Único lugar que sabe de HTTP: arma la URL de cada microservicio, manda el JWT en
 * {@code Authorization: Bearer <token>}, lo renueva antes de que caduque y traduce los errores a {@link ApiException}.
 *
 * <p>Una respuesta 401 con token se reintenta UNA vez tras renovar; si aun así falla (token vencido o revocado y
 * refresh inservible) se limpia la sesión y se lanza {@link SessionExpiredException} para volver al login.
 */
public final class HttpApi {

    /** Los seis microservicios REST más el servidor de rastreo. */
    public enum Service { AUTH, BOOKS, USERS, AUTHORS, PEDIDOS, PAGOS, TRACKING }

    public record Response(int status, JsonNode body, HttpHeaders headers) {
    }

    private static final Duration TIMEOUT = Duration.ofSeconds(10);
    /** Se renueva el JWT cuando faltan menos de 3 minutos de los 20. */
    public static final long REFRESH_MARGIN_SECONDS = 180;

    private final ServiceUrls urls;
    private final Session session;
    private final HttpClient client;
    private final Object refreshLock = new Object();

    public HttpApi(ServiceUrls urls, Session session) {
        this.urls = urls;
        this.session = session;
        // El login deja una cookie de sesión de Flask que /logout necesita; el JWT va aparte, en la cabecera.
        this.client = HttpClient.newBuilder().cookieHandler(new CookieManager()).connectTimeout(Duration.ofSeconds(6)).build();
    }

    public ServiceUrls urls() {
        return urls;
    }

    public Session session() {
        return session;
    }

    // ------------------------------------------------------------------ atajos
    public JsonNode get(Service service, String path) {
        return call(service, "GET", path, null, null, null, true).body();
    }

    public JsonNode get(Service service, String path, Map<String, String> query) {
        return call(service, "GET", path, query, null, null, true).body();
    }

    public JsonNode post(Service service, String path, Object body) {
        return call(service, "POST", path, null, body, null, true).body();
    }

    public JsonNode delete(Service service, String path) {
        return call(service, "DELETE", path, null, null, null, true).body();
    }

    public Response call(Service service, String method, String path, Map<String, String> query, Object body,
                         Map<String, String> headers, boolean auth) {
        return call(service, method, path, query, body, headers, auth, true);
    }

    // ------------------------------------------------------------------- núcleo
    private Response call(Service service, String method, String path, Map<String, String> query, Object body,
                          Map<String, String> headers, boolean auth, boolean retryOn401) {
        boolean withToken = auth && session.active();
        if (withToken && service != Service.AUTH) {
            ensureFresh();
        }
        HttpRequest.Builder request = HttpRequest.newBuilder(buildUri(service, path, query)).timeout(TIMEOUT)
                .header("Accept", "application/json");
        if (withToken) {
            request.header("Authorization", "Bearer " + session.accessToken());
        }
        if (headers != null) {
            headers.forEach(request::header);
        }
        HttpRequest.BodyPublisher publisher = HttpRequest.BodyPublishers.noBody();
        if (body != null) {
            request.header("Content-Type", "application/json");
            publisher = HttpRequest.BodyPublishers.ofString(Json.write(body), StandardCharsets.UTF_8);
        }
        HttpResponse<String> response = send(request.method(method, publisher).build());

        if (response.statusCode() == 401 && withToken && retryOn401 && service != Service.AUTH) {
            if (refreshTokens()) {
                return call(service, method, path, query, body, headers, auth, false);
            }
            session.clear();
            throw new SessionExpiredException("Tu sesión expiró o fue cerrada. Inicia sesión de nuevo.");
        }
        JsonNode json = parseBody(response);
        if (response.statusCode() >= 400) {
            throw toException(response, json);
        }
        return new Response(response.statusCode(), json, response.headers());
    }

    private HttpResponse<String> send(HttpRequest request) {
        try {
            return client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(0, "interrupted", "La operación fue interrumpida.");
        } catch (java.net.http.HttpTimeoutException e) {
            throw new ApiException(0, "timeout", "El servidor tardó demasiado en responder (tiempo de espera agotado).");
        } catch (IOException e) {
            throw new ApiException(0, "network", "No se pudo conectar con el servidor. Revisa la configuración de conexión "
                    + "o si el microservicio está encendido.");
        }
    }

    private URI buildUri(Service service, String path, Map<String, String> query) {
        Map<String, String> params = new LinkedHashMap<>();
        if (service != Service.TRACKING) {
            params.put("format", "json");   // los servicios responden XML por omisión
        }
        if (query != null) {
            params.putAll(query);
        }
        StringBuilder sb = new StringBuilder(base(service)).append(path);
        char sep = '?';
        for (Map.Entry<String, String> e : params.entrySet()) {
            sb.append(sep).append(URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8)).append('=')
                    .append(URLEncoder.encode(e.getValue(), StandardCharsets.UTF_8));
            sep = '&';
        }
        return URI.create(sb.toString());
    }

    private String base(Service service) {
        return switch (service) {
            case AUTH -> urls.auth();
            case BOOKS -> urls.books();
            case USERS -> urls.users();
            case AUTHORS -> urls.authors();
            case PEDIDOS -> urls.pedidos();
            case PAGOS -> urls.pagos();
            case TRACKING -> urls.tracking();
        };
    }

    private static JsonNode parseBody(HttpResponse<String> response) {
        String text = response.body();
        if (text == null || text.isBlank()) {
            return Json.MAPPER.createObjectNode();
        }
        try {
            return Json.parse(text);
        } catch (IllegalArgumentException e) {
            return Json.MAPPER.createObjectNode();
        }
    }

    /** Los servicios responden {"error": {"code", "message", "details"}}; Books a veces {"error": "texto"}. */
    static ApiException toException(HttpResponse<String> response, JsonNode json) {
        int status = response.statusCode();
        String contentType = response.headers().firstValue("Content-Type").orElse("");
        if (json.isEmpty() && contentType.contains("text/html")) {
            return new ApiException(status, "network_blocked", "Una red o firewall bloqueó la conexión (página de filtro web, HTTP "
                    + status + "). No es un problema de tu usuario ni de tu contraseña: cambia de red e intenta de nuevo.");
        }
        JsonNode error = json.path("error");
        if (error.isObject()) {
            StringBuilder message = new StringBuilder(Json.text(error, "message",
                    "El servidor respondió con un error (HTTP " + status + ")."));
            StringBuilder details = new StringBuilder();
            for (JsonNode d : error.path("details")) {
                String field = Json.text(d, "field");
                String msg = Json.text(d, "message");
                if (!msg.isBlank()) {
                    details.append(details.length() > 0 ? "; " : "").append(field.isBlank() ? "" : field + ": ").append(msg);
                }
            }
            if (details.length() > 0) {
                message.append(": ").append(details);
            }
            return new ApiException(status, Json.text(error, "code"), message.toString());
        }
        if (error.isTextual()) {
            return new ApiException(status, null, error.asText());
        }
        return new ApiException(status, null, "El servidor respondió con un error (HTTP " + status + ").");
    }

    // ------------------------------------------------------------------- JWT
    /** Renueva el JWT si le quedan menos de {@link #REFRESH_MARGIN_SECONDS}. Devuelve true si se renovó. */
    public boolean ensureFresh() {
        if (session.active() && session.refreshToken() != null && session.secondsLeft() < REFRESH_MARGIN_SECONDS) {
            return refreshTokens();
        }
        return false;
    }

    /** {@code POST /token/refresh}: el refresh token es de un solo uso; el servidor devuelve uno nuevo. */
    public boolean refreshTokens() {
        synchronized (refreshLock) {
            String refresh = session.refreshToken();
            if (refresh == null) {
                return false;
            }
            try {
                Response r = call(Service.AUTH, "POST", "/token/refresh", null, Map.of("refresh_token", refresh), null, false, false);
                session.setTokens(r.body());
                return true;
            } catch (ApiException e) {
                if (e.status() == 400 || e.status() == 401) {
                    session.clear();   // vencido, ya usado o sesión cerrada: ya no sirve de nada
                }
                return false;
            }
        }
    }
}
