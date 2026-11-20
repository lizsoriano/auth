package mx.udem.library;

import mx.udem.library.api.ApiException;
import mx.udem.library.api.Backend;
import mx.udem.library.api.HttpApi.Service;
import mx.udem.library.api.SessionExpiredException;
import mx.udem.library.config.ServiceUrls;
import mx.udem.library.model.User;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HttpApiTest {

    private FakeServer server;
    private Backend backend;

    private static String loginBody(String token, String refresh) {
        return "{\"token\":\"" + token + "\",\"refresh_token\":\"" + refresh + "\",\"token_expires_in_seconds\":1200,"
                + "\"user\":{\"id\":7,\"email\":\"ana@example.com\",\"display_name\":\"Ana\",\"nombre\":\"Ana\",\"role\":\"customer\",\"role_id\":3}}";
    }

    @BeforeEach
    void setUp() throws Exception {
        server = new FakeServer();
        String u = server.url();
        backend = new Backend(new ServiceUrls(u + "/auth", u + "/books", u + "/users", u + "/authors", u + "/pedidos", u + "/pagos", u + "/gps", ""));
    }

    @AfterEach
    void tearDown() {
        server.close();
    }

    @Test
    void loginSendsCredentialsStoresTokensAndReturnsTheUser() {
        server.on(r -> FakeServer.Res.json(200, loginBody("jwt-1", "ref-1")));
        User user = backend.auth().login("ana@example.com", "secreto");
        assertEquals("Ana", user.displayName());
        assertEquals(3, user.roleId());
        assertEquals("jwt-1", backend.session().accessToken());
        FakeServer.Req req = server.requestsTo("/auth/login").get(0);
        assertEquals("POST", req.method());
        assertTrue(req.body().contains("\"email\":\"ana@example.com\""));
        assertEquals("", req.header("Authorization"), "el login no lleva Bearer");
        assertTrue(req.query().contains("format=json"));
    }

    @Test
    void protectedCallsCarryTheBearerToken() {
        server.on(r -> r.path().equals("/auth/login") ? FakeServer.Res.json(200, loginBody("jwt-1", "ref-1"))
                : FakeServer.Res.json(200, "{\"user\":{\"user_id\":7,\"email\":\"ana@example.com\",\"role_id\":3,\"role_name\":\"customer\"}}"));
        backend.auth().login("ana@example.com", "x");
        User me = backend.users().me();
        assertEquals("ana@example.com", me.email());
        assertEquals("Bearer jwt-1", server.requestsTo("/users/users/me").get(0).header("Authorization"));
    }

    @Test
    void anExpiredTokenIsRenewedOnceAndTheCallIsRetried() {
        AtomicInteger orders = new AtomicInteger();
        server.on(r -> switch (r.path()) {
            case "/auth/login" -> FakeServer.Res.json(200, loginBody("old", "ref-1"));
            case "/auth/token/refresh" -> FakeServer.Res.json(200, loginBody("new", "ref-2"));
            case "/pedidos/pedidos" -> orders.incrementAndGet() == 1 && r.header("Authorization").equals("Bearer old")
                    ? FakeServer.Res.json(401, "{\"error\":{\"code\":\"token_expired\",\"message\":\"vencido\"}}")
                    : FakeServer.Res.json(200, "{\"orders\":[]}");
            default -> FakeServer.Res.json(404, "{}");
        });
        backend.auth().login("ana@example.com", "x");
        assertTrue(backend.orders().list(10).isEmpty());
        assertEquals("new", backend.session().accessToken());
        assertEquals("ref-1", server.requestsTo("/auth/token/refresh").get(0).body().replaceAll(".*\"refresh_token\":\"([^\"]+)\".*", "$1"));
        assertEquals("Bearer new", server.requestsTo("/pedidos/pedidos").get(1).header("Authorization"));
    }

    @Test
    void ifTheRefreshTokenIsUselessTheSessionExpires() {
        server.on(r -> switch (r.path()) {
            case "/auth/login" -> FakeServer.Res.json(200, loginBody("old", "ref-1"));
            case "/auth/token/refresh" -> FakeServer.Res.json(401, "{\"error\":{\"code\":\"token_revoked\",\"message\":\"revocado\"}}");
            default -> FakeServer.Res.json(401, "{\"error\":{\"code\":\"token_expired\",\"message\":\"vencido\"}}");
        });
        backend.auth().login("ana@example.com", "x");
        assertThrows(SessionExpiredException.class, () -> backend.orders().list(10));
        assertFalse(backend.session().active(), "la sesión se limpia y se pide autenticarse de nuevo");
    }

    @Test
    void serverErrorsKeepTheCodeAndTheFieldDetails() {
        server.on(r -> FakeServer.Res.json(400, "{\"error\":{\"code\":\"validation_error\",\"message\":\"Datos inválidos\","
                + "\"details\":[{\"field\":\"method\",\"message\":\"debe ser uno de: tarjeta\"}]}}"));
        ApiException e = assertThrows(ApiException.class, () -> backend.http().get(Service.PAGOS, "/x"));
        assertEquals(400, e.status());
        assertEquals("validation_error", e.code());
        assertTrue(e.getMessage().contains("method: debe ser uno de: tarjeta"));
    }

    @Test
    void booksSometimesAnswersWithAPlainErrorString() {
        server.on(r -> FakeServer.Res.json(404, "{\"error\":\"No existe ese libro\"}"));
        ApiException e = assertThrows(ApiException.class, () -> backend.books().get("123", null));
        assertEquals("No existe ese libro", e.getMessage());
    }

    @Test
    void aDeadServerIsReportedAsANetworkError() throws Exception {
        server.close();
        ApiException e = assertThrows(ApiException.class, () -> backend.books().catalog());
        assertTrue(e.isNetwork());
    }

    @Test
    void trackingCallsDoNotAddTheFormatParameter() {
        server.on(r -> FakeServer.Res.json(200, "{\"tracking\":{\"code\":\"LIB-MTY-2026-000007\"}}"));
        backend.session().setTokens(mx.udem.library.api.Json.parse("{\"token\":\"t\",\"refresh_token\":\"r\"}"));
        assertEquals("LIB-MTY-2026-000007", backend.tracking().open(7).path("code").asText());
        assertEquals(null, server.requestsTo("/gps/tracking").get(0).query());
    }
}
