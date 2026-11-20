package mx.udem.library;

import mx.udem.library.api.Backend;
import mx.udem.library.api.Json;
import mx.udem.library.cart.Cart;
import mx.udem.library.cart.PurchaseService;
import mx.udem.library.config.ServiceUrls;
import mx.udem.library.model.Book;
import mx.udem.library.model.Order;
import mx.udem.library.model.TrackingCode;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ShoppingTest {

    private static Book book(String isbn, String title, String price, int stock) {
        return new Book(1, isbn, title, new BigDecimal(price), "Ficción", stock, 1949, "George Orwell", null);
    }

    // ---------------------------------------------------------------- cesta
    @Test
    void cartAddsQuantitiesWithoutExceedingStockAndComputesTotals() {
        Cart cart = new Cart();
        Book a = book("111", "1984", "219.00", 3);
        Book b = book("222", "Dune", "100.50", 10);
        assertEquals(2, cart.add(a, 2));
        assertEquals(1, cart.add(a, 5), "solo cabe uno más: el stock es 3");
        assertEquals(0, cart.add(a, 1), "ya está al tope");
        cart.add(b, 2);
        assertEquals(5, cart.units());
        assertEquals(new BigDecimal("858.00"), cart.subtotal());   // 3 × 219.00 + 2 × 100.50
        assertEquals(cart.subtotal(), cart.total());
    }

    @Test
    void cartQuantitiesCanBeChangedAndLinesRemoved() {
        Cart cart = new Cart();
        cart.add(book("111", "1984", "10.00", 5), 1);
        cart.setQuantity("111", 4);
        assertEquals(4, cart.units());
        cart.setQuantity("111", 99);
        assertEquals(5, cart.units(), "no pasa del stock");
        cart.setQuantity("111", 0);
        assertTrue(cart.isEmpty(), "cantidad menor a 1 elimina la línea");
        cart.add(book("222", "Dune", "1.00", 2), 1);
        cart.remove("222");
        assertTrue(cart.isEmpty());
    }

    @Test
    void cartNotifiesListeners() {
        Cart cart = new Cart();
        int[] changes = {0};
        cart.onChange(() -> changes[0]++);
        cart.add(book("111", "1984", "10.00", 5), 1);
        cart.setQuantity("111", 2);
        cart.clear();
        assertEquals(3, changes[0]);
    }

    // ------------------------------------------------------------- rastreo
    @Test
    void trackingCodeFormatAndParsing() {
        assertEquals("LIB-MTY-2026-000125", TrackingCode.format(2026, 125));
        assertEquals("LIB-MTY-2026-000125", TrackingCode.normalize("  lib-mty-2026-000125 "));
        assertEquals("", TrackingCode.normalize("LIB-MTY-26-125"));
        assertEquals(125, TrackingCode.orderId("LIB-MTY-2026-000125").orElseThrow());
        assertTrue(TrackingCode.orderId("hola").isEmpty());
        Order o = Order.from(Json.parse("{\"order_id\":125,\"user_id\":7,\"status\":\"pagado\",\"total\":10.5,\"created_at\":\"2026-11-06T21:01:40+00:00\",\"items\":[]}"));
        assertEquals("LIB-MTY-2026-000125", o.trackingCode());
        assertTrue(o.trackable());
    }

    // -------------------------------------------------------------- compra
    private FakeServer server;
    private Backend backend;

    @BeforeEach
    void setUp() throws Exception {
        server = new FakeServer();
        String u = server.url();
        backend = new Backend(new ServiceUrls(u + "/auth", u + "/books", u + "/users", u + "/authors", u + "/pedidos", u + "/pagos", u + "/gps", ""));
        backend.session().setTokens(Json.parse("{\"token\":\"jwt\",\"refresh_token\":\"r\",\"token_expires_in_seconds\":1200}"));
    }

    @AfterEach
    void tearDown() {
        server.close();
    }

    private PurchaseService purchases() {
        return new PurchaseService(backend.books(), backend.orders(), backend.payments(), backend.tracking());
    }

    @Test
    void validationDetectsPriceChangesAndMissingStockAndRefreshesTheCart() {
        server.on(r -> FakeServer.Res.json(200, "{\"bookId\":1,\"isbn\":\"111\",\"title\":\"1984\",\"price\":250.0,\"stock\":1,\"category\":\"Ficción\",\"publicationYear\":1949,\"authors\":\"Orwell\"}"));
        Cart cart = new Cart();
        cart.add(book("111", "1984", "219.00", 5), 3);
        PurchaseService.Validation v = purchases().validate(cart);
        assertFalse(v.ok());
        assertEquals(2, v.issues().size());
        assertTrue(v.issues().get(0).contains("de $219.00 a $250.00"));
        assertTrue(v.issues().get(1).contains("solo quedan 1"));
        assertEquals(new BigDecimal("250.00"), cart.lines().get(0).book().price(), "la cesta queda con el precio vigente");
        assertEquals(1, cart.lines().get(0).quantity(), "y sin pasar del stock");
    }

    @Test
    void checkoutCreatesTheOrderPaysItWithTheExactTotalAndStartsTracking() {
        List<String> steps = new ArrayList<>();
        server.on(r -> {
            if (r.path().equals("/pedidos/pedidos") && r.method().equals("POST")) {
                return FakeServer.Res.json(201, "{\"order\":{\"order_id\":125,\"user_id\":7,\"status\":\"pendiente\",\"total\":219.0,\"created_at\":\"2026-11-06T10:00:00+00:00\",\"items\":[{\"isbn\":\"111\",\"title\":\"1984\",\"quantity\":1,\"unit_price\":219.0}]}}");
            }
            if (r.path().equals("/pagos/pagos")) {
                return FakeServer.Res.json(201, "{\"payment\":{\"payment_id\":9,\"order_id\":125,\"amount\":219.0,\"method\":\"tarjeta\",\"status\":\"aprobado\"}}");
            }
            if (r.path().equals("/pedidos/pedidos/125")) {
                return FakeServer.Res.json(200, "{\"order\":{\"order_id\":125,\"user_id\":7,\"status\":\"pagado\",\"total\":219.0,\"created_at\":\"2026-11-06T10:00:00+00:00\",\"items\":[]}}");
            }
            if (r.path().equals("/gps/tracking")) {
                return FakeServer.Res.json(200, "{\"tracking\":{\"code\":\"LIB-MTY-2026-000125\"}}");
            }
            return FakeServer.Res.json(404, "{}");
        });
        Cart cart = new Cart();
        cart.add(book("111", "1984", "219.00", 5), 1);
        PurchaseService.Result result = purchases().checkout(cart, "tarjeta", steps::add);

        assertEquals("pagado", result.order().status());
        assertEquals("aprobado", result.payment().status());
        assertEquals("LIB-MTY-2026-000125", result.trackingCode());
        assertTrue(result.trackingStarted());
        assertTrue(cart.isEmpty(), "la cesta se vacía tras pagar");
        assertEquals(3, steps.size());

        FakeServer.Req order = server.requestsTo("/pedidos/pedidos").get(0);
        assertTrue(order.body().contains("\"isbn\":\"111\"") && order.body().contains("\"quantity\":1"));
        FakeServer.Req pay = server.requestsTo("/pagos/pagos").get(0);
        assertTrue(pay.body().contains("\"order_id\":125") && pay.body().contains("\"method\":\"tarjeta\""));
        assertTrue(pay.body().contains("219"), "paga exactamente el total del pedido");
        assertFalse(pay.header("Idempotency-Key").isBlank(), "evita el doble cobro al reintentar");
        assertEquals("Bearer jwt", pay.header("Authorization"));
    }

    @Test
    void ifTheTrackingServerIsDownThePurchaseStillSucceedsWithADeterministicCode() {
        server.on(r -> {
            if (r.path().equals("/pedidos/pedidos") && r.method().equals("POST")) {
                return FakeServer.Res.json(201, "{\"order\":{\"order_id\":8,\"user_id\":7,\"status\":\"pendiente\",\"total\":10.0,\"created_at\":\"2026-11-06T10:00:00+00:00\",\"items\":[]}}");
            }
            if (r.path().equals("/pagos/pagos")) {
                return FakeServer.Res.json(201, "{\"payment\":{\"payment_id\":1,\"order_id\":8,\"amount\":10.0,\"method\":\"efectivo\",\"status\":\"aprobado\"}}");
            }
            if (r.path().equals("/pedidos/pedidos/8")) {
                return FakeServer.Res.json(200, "{\"order\":{\"order_id\":8,\"user_id\":7,\"status\":\"pagado\",\"total\":10.0,\"created_at\":\"2026-11-06T10:00:00+00:00\",\"items\":[]}}");
            }
            return FakeServer.Res.json(503, "{\"error\":{\"code\":\"tracking_disabled\",\"message\":\"apagado\"}}");
        });
        Cart cart = new Cart();
        cart.add(book("111", "1984", "10.00", 5), 1);
        PurchaseService.Result result = purchases().checkout(cart, "efectivo", s -> { });
        assertFalse(result.trackingStarted());
        assertEquals("LIB-MTY-2026-000008", result.trackingCode());
    }
}
