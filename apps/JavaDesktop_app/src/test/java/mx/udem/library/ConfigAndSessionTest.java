package mx.udem.library;

import mx.udem.library.api.Json;
import mx.udem.library.api.Session;
import mx.udem.library.config.ConfigStore;
import mx.udem.library.config.ServiceUrls;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ConfigAndSessionTest {

    @Test
    void localPresetUsesOnePortPerService() {
        ServiceUrls u = ServiceUrls.local("localhost");
        assertEquals("http://localhost:15000", u.auth());
        assertEquals("http://localhost:15005", u.pagos());
        assertEquals("ws://localhost:5900/ws/tracking", u.trackingWsUrl());
    }

    @Test
    void vmPresetUsesNginxPrefixesAndAcceptsAFullUrl() {
        ServiceUrls u = ServiceUrls.vm("http://34.51.63.13/");
        assertEquals("http://34.51.63.13/api/login", u.auth());
        assertEquals("http://34.51.63.13/api/books", u.books());
        assertEquals("http://34.51.63.13/api/pedidos", u.pedidos());
        assertEquals("http://34.51.63.13/api/gps", u.tracking());
        assertEquals("ws://34.51.63.13/api/gps/ws/tracking", u.trackingWsUrl());
    }

    @Test
    void gatewayIsASingleAddressAndEveryServiceIsARoute() {
        ServiceUrls u = ServiceUrls.gateway("localhost:8080");
        assertEquals("http://localhost:8080/api/login", u.auth());
        assertEquals("http://localhost:8080/api/books", u.books());
        assertEquals("http://localhost:8080/api/users", u.users());
        assertEquals("http://localhost:8080/api/authors", u.authors());
        assertEquals("http://localhost:8080/api/pedidos", u.pedidos());
        assertEquals("http://localhost:8080/api/pagos", u.pagos());
        assertEquals("ws://localhost:8080/api/gps/ws/tracking", u.trackingWsUrl());
        assertEquals("http://localhost:8080/library/uploads/a.jpg", u.imageUrl("/uploads/a.jpg"));
        assertEquals("http://localhost:8080", u.gatewayBase());
    }

    @Test
    void gatewayAddressIsNormalised() {
        assertEquals("http://34.51.109.238", ServiceUrls.gateway("34.51.109.238").gatewayBase());
        assertEquals("http://34.51.109.238", ServiceUrls.gateway("  http://34.51.109.238/algo/mas  ").gatewayBase());
        assertEquals("https://api.example.com:8443", ServiceUrls.gateway("https://api.example.com:8443/").gatewayBase());
        assertEquals("wss://api.example.com:8443/api/gps/ws/tracking", ServiceUrls.gateway("https://api.example.com:8443").trackingWsUrl());
        assertEquals(ServiceUrls.DEFAULT_GATEWAY, ServiceUrls.gateway("").gatewayBase());
        assertEquals("", ServiceUrls.local("localhost").gatewayBase(), "direcciones sueltas: no hay una sola");
    }

    @Test
    void secureTrackingUrlsBecomeWss() {
        ServiceUrls u = new ServiceUrls("a", "b", "c", "d", "e", "f", "https://gps.example.com/", "");
        assertEquals("wss://gps.example.com/ws/tracking", u.trackingWsUrl());
    }

    @Test
    void coverPathsAreResolvedAgainstTheImagesHost() {
        ServiceUrls u = ServiceUrls.vm("1.2.3.4");
        assertEquals("http://1.2.3.4/library/uploads/seed/x.jpg", u.imageUrl("/uploads/seed/x.jpg"));
        assertEquals("http://otro/x.jpg", u.imageUrl("http://otro/x.jpg"));
        assertNull(u.imageUrl(null));
        assertNull(new ServiceUrls("a", "b", "c", "d", "e", "f", "g", "").imageUrl("/x.jpg"));
    }

    @Test
    void configIsSavedAndLoadedWithoutAnySecret(@TempDir Path dir) throws Exception {
        ConfigStore store = new ConfigStore(dir.resolve("sub/config.json"));
        assertEquals(ServiceUrls.gateway(ServiceUrls.DEFAULT_GATEWAY), store.load(), "sin archivo: el gateway de esta computadora");
        ServiceUrls vm = ServiceUrls.vm("34.51.63.13");
        store.save(vm);
        assertEquals(vm, store.load());
        String text = Files.readString(dir.resolve("sub/config.json"));
        assertFalse(text.toLowerCase().contains("password") || text.toLowerCase().contains("token"));
    }

    @Test
    void sessionTracksTokensClaimsAndClearsEverything() {
        String payload = Base64.getUrlEncoder().withoutPadding().encodeToString(
                "{\"user_id\":7,\"role_id\":3,\"iss\":\"library-login\",\"exp\":9999999999}".getBytes(StandardCharsets.UTF_8));
        String jwt = "aaa." + payload + ".bbb";
        Session s = new Session();
        AtomicReference<String> notified = new AtomicReference<>();
        s.onNewToken(notified::set);
        assertFalse(s.active());
        s.setTokens(Json.parse("{\"token\":\"" + jwt + "\",\"refresh_token\":\"r1\",\"token_expires_in_seconds\":1200}"));
        assertTrue(s.active());
        assertEquals(jwt, notified.get(), "el rastreo se entera del JWT nuevo");
        assertEquals(7, s.claims().path("user_id").asInt());
        assertTrue(s.secondsLeft() > 1190 && s.secondsLeft() <= 1200);
        s.clear();
        assertFalse(s.active());
        assertEquals(0, s.secondsLeft());
        assertTrue(s.claims().isEmpty());
    }
}
