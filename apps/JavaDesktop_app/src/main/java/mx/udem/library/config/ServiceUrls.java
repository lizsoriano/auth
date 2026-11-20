package mx.udem.library.config;

import java.net.URI;

/**
 * Dirección base de cada microservicio. El cliente nunca arma una URL fuera de aquí.
 *
 * <p>La app habla con UNA sola dirección, la del <b>API Gateway</b> (Nginx → gateway → servicios), y cada servicio es una
 * ruta de esa dirección: {@code /api/login}, {@code /api/books}, {@code /api/users}, {@code /api/authors}, {@code /api/pedidos},
 * {@code /api/pagos}, {@code /api/gps} (rastreo, con su WebSocket) y {@code /library} (portadas: el monolito vive en "/"). Así cambiar de equipo o de
 * instancia es cambiar una sola dirección ({@link #gateway(String)}).
 *
 * <p>Los ocho valores siguen siendo direcciones completas para poder apuntar a servicios sueltos (pruebas,
 * {@link #local(String)} con un puerto por servicio), pero ya no hay que escribirlas a mano.
 * {@code tracking} es el servidor Flask + Flask-Sock de rastreo GPS y {@code images} el host que sirve las portadas
 * ({@code /uploads/...} lo publica el monolito, no Books).
 */
public record ServiceUrls(String auth, String books, String users, String authors, String pedidos, String pagos,
                          String tracking, String images) {

    /** Dirección por omisión del gateway (el de esta misma computadora). */
    public static final String DEFAULT_GATEWAY = "http://localhost:8080";

    public ServiceUrls {
        auth = clean(auth);
        books = clean(books);
        users = clean(users);
        authors = clean(authors);
        pedidos = clean(pedidos);
        pagos = clean(pagos);
        tracking = clean(tracking);
        images = clean(images);
    }

    public static ServiceUrls local(String host) {
        String base = "http://" + URI.create(baseOf(host.isBlank() ? "localhost" : host)).getHost();
        return new ServiceUrls(base + ":15000", base + ":15001", base + ":15002", base + ":15003", base + ":15004",
                base + ":15005", base + ":5900", base + ":3000/library");
    }

    /** Todas las rutas colgando de una sola dirección: la del API Gateway (con puerto si lo lleva: {@code localhost:8080}). */
    public static ServiceUrls gateway(String address) {
        String base = baseOf(address == null || address.isBlank() ? DEFAULT_GATEWAY : address);
        return new ServiceUrls(base + "/api/login", base + "/api/books", base + "/api/users", base + "/api/authors",
                base + "/api/pedidos", base + "/api/pagos", base + "/api/gps", base + "/library");
    }

    /** Igual que {@link #gateway(String)}: la instancia de GCP se publica detrás de Nginx → gateway, en el puerto 80. */
    public static ServiceUrls vm(String host) {
        return gateway(host);
    }

    /** La dirección única del gateway si estas URLs cuelgan de una ({@code http://IP[:puerto]}); vacío si son sueltas. */
    public String gatewayBase() {
        for (String suffix : new String[] {"/api/login", "/auth"}) {     // "/auth": configuración guardada por versiones anteriores
            if (auth.endsWith(suffix)) {
                return auth.substring(0, auth.length() - suffix.length());
            }
        }
        return "";
    }

    /** URL del WebSocket de rastreo derivada de la del servidor de rastreo (http→ws, https→wss). */
    public String trackingWsUrl() {
        return tracking.replaceFirst("^http", "ws") + "/ws/tracking";
    }

    /** Une la base de las portadas con la ruta que devuelve Books (p. ej. {@code /uploads/seed/978-1.jpg}). */
    public String imageUrl(String path) {
        if (path == null || path.isBlank()) {
            return null;
        }
        if (path.startsWith("http://") || path.startsWith("https://")) {
            return path;
        }
        return images.isEmpty() ? null : images + (path.startsWith("/") ? path : "/" + path);
    }

    private static String clean(String value) {
        if (value == null) {
            return "";
        }
        String v = value.trim();
        while (v.endsWith("/")) {
            v = v.substring(0, v.length() - 1);
        }
        return v;
    }

    /** Dirección sin ruta: {@code 34.1.2.3}, {@code localhost:8080/x} o {@code https://host/} → {@code scheme://host[:puerto]}. */
    static String baseOf(String text) {
        String t = text.trim();
        if (!t.contains("://")) {
            t = "http://" + t;
        }
        try {
            URI uri = URI.create(t);
            if (uri.getHost() == null) {
                return clean(t);
            }
            return uri.getScheme() + "://" + uri.getHost() + (uri.getPort() >= 0 ? ":" + uri.getPort() : "");
        } catch (IllegalArgumentException e) {
            return clean(t);
        }
    }
}
