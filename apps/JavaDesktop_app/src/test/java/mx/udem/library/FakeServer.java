package mx.udem.library;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Function;

/** Servidor HTTP mínimo (JDK) para probar el cliente sin red ni microservicios reales. */
public final class FakeServer implements AutoCloseable {

    public record Req(String method, String path, String query, Map<String, String> headers, String body) {
        public String header(String name) {
            return headers.getOrDefault(name.toLowerCase(), "");
        }
    }

    public record Res(int status, String body) {
        public static Res json(int status, String body) {
            return new Res(status, body);
        }
    }

    private final HttpServer server;
    public final List<Req> requests = new CopyOnWriteArrayList<>();
    private volatile Function<Req, Res> handler = r -> new Res(404, "{}");

    public FakeServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", this::handle);
        server.start();
    }

    public FakeServer on(Function<Req, Res> handler) {
        this.handler = handler;
        return this;
    }

    public String url() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    public List<Req> requestsTo(String path) {
        List<Req> out = new ArrayList<>();
        requests.stream().filter(r -> r.path().equals(path)).forEach(out::add);
        return out;
    }

    private void handle(HttpExchange ex) throws IOException {
        Map<String, String> headers = new java.util.HashMap<>();
        ex.getRequestHeaders().forEach((k, v) -> headers.put(k.toLowerCase(), v.get(0)));
        String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        Req req = new Req(ex.getRequestMethod(), ex.getRequestURI().getPath(), ex.getRequestURI().getRawQuery(), headers, body);
        requests.add(req);
        Res res = handler.apply(req);
        byte[] bytes = res.body().getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(res.status(), bytes.length);
        ex.getResponseBody().write(bytes);
        ex.close();
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
