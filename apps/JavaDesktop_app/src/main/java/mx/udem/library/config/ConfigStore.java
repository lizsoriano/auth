package mx.udem.library.config;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Guarda las direcciones de los servicios en {@code ~/.library-desktop/config.json}. Aquí NO se guarda nada secreto:
 * ni contraseñas ni tokens (la sesión vive solo en memoria).
 */
public final class ConfigStore {

    private static final ObjectMapper JSON = new ObjectMapper();
    private final Path file;

    public ConfigStore() {
        this(Path.of(System.getProperty("user.home"), ".library-desktop", "config.json"));
    }

    public ConfigStore(Path file) {
        this.file = file;
    }

    public ServiceUrls load() {
        ServiceUrls fallback = ServiceUrls.gateway(ServiceUrls.DEFAULT_GATEWAY);
        if (!Files.isRegularFile(file)) {
            return fallback;
        }
        try {
            JsonNode n = JSON.readTree(Files.readString(file));
            return new ServiceUrls(text(n, "auth", fallback.auth()), text(n, "books", fallback.books()),
                    text(n, "users", fallback.users()), text(n, "authors", fallback.authors()),
                    text(n, "pedidos", fallback.pedidos()), text(n, "pagos", fallback.pagos()),
                    text(n, "tracking", fallback.tracking()), text(n, "images", fallback.images()));
        } catch (IOException | RuntimeException e) {
            return fallback;
        }
    }

    public void save(ServiceUrls urls) throws IOException {
        ObjectNode n = JSON.createObjectNode();
        n.put("auth", urls.auth()).put("books", urls.books()).put("users", urls.users()).put("authors", urls.authors())
                .put("pedidos", urls.pedidos()).put("pagos", urls.pagos()).put("tracking", urls.tracking())
                .put("images", urls.images());
        Files.createDirectories(file.getParent());
        Files.writeString(file, JSON.writerWithDefaultPrettyPrinter().writeValueAsString(n));
    }

    private static String text(JsonNode n, String key, String fallback) {
        JsonNode v = n.get(key);
        return v != null && v.isTextual() && !v.asText().isBlank() ? v.asText() : fallback;
    }
}
