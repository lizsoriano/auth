package mx.udem.library.cart;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.ApiException;
import mx.udem.library.api.BooksApi;
import mx.udem.library.api.OrdersApi;
import mx.udem.library.api.PaymentFailedException;
import mx.udem.library.api.PaymentsApi;
import mx.udem.library.api.SessionExpiredException;
import mx.udem.library.api.TrackingApi;
import mx.udem.library.model.Book;
import mx.udem.library.model.CartLine;
import mx.udem.library.model.Order;
import mx.udem.library.model.Payment;
import mx.udem.library.model.TrackingCode;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.function.Consumer;

/**
 * Flujo de compra simulada sobre los servicios reales: validar la cesta contra Books, crear el pedido en Pedidos,
 * pagarlo en Pagos y pedir el seguimiento al servidor de rastreo. Ningún paso inventa resultados: si un servicio
 * falla, el error sube tal cual.
 */
public final class PurchaseService {

    /** @param issues diferencias encontradas (precio cambiado, stock insuficiente); vacío = la cesta es válida. */
    public record Validation(List<String> issues) {
        public boolean ok() {
            return issues.isEmpty();
        }
    }

    /**
     * @param trackingStarted false si el servidor de rastreo no respondió: el código sigue siendo válido
     *                        y se podrá rastrear más tarde, pero todavía no hay simulación en marcha.
     */
    public record Result(Order order, Payment payment, String trackingCode, boolean trackingStarted) {
    }

    private final BooksApi books;
    private final OrdersApi orders;
    private final PaymentsApi payments;
    private final TrackingApi tracking;

    public PurchaseService(BooksApi books, OrdersApi orders, PaymentsApi payments, TrackingApi tracking) {
        this.books = books;
        this.orders = orders;
        this.payments = payments;
        this.tracking = tracking;
    }

    /** Compara cada línea con el libro vigente ({@code GET /books/{isbn}}) y actualiza la cesta con los datos frescos. */
    public Validation validate(Cart cart) {
        List<String> issues = new ArrayList<>();
        for (CartLine line : cart.lines()) {
            Book old = line.book();
            Book fresh;
            try {
                fresh = books.get(old.isbn(), old.coverPath());
            } catch (ApiException e) {
                if (e.status() == 404) {
                    issues.add("«" + old.title() + "» ya no está en el catálogo.");
                    continue;
                }
                throw e;
            }
            if (fresh.price().compareTo(old.price()) != 0) {
                issues.add("El precio de «" + old.title() + "» cambió de $" + old.price() + " a $" + fresh.price() + ".");
            }
            if (fresh.stock() < line.quantity()) {
                issues.add("«" + old.title() + "»: solo quedan " + fresh.stock() + " ejemplares (pediste " + line.quantity() + ").");
            }
            cart.refresh(fresh);
        }
        return new Validation(issues);
    }

    public Result checkout(Cart cart, String method, Consumer<String> progress) {
        if (cart.isEmpty()) {
            throw new IllegalStateException("La cesta está vacía.");
        }
        progress.accept("Creando el pedido…");
        Order created = orders.create(cart.lines());
        return pay(created, method, progress, cart);
    }

    /** Paga un pedido pendiente (también sirve para reintentar desde «Mis compras»). */
    public Result pay(Order order, String method, Consumer<String> progress, Cart cartToClear) {
        progress.accept("Registrando el pago simulado…");
        Payment payment;
        try {
            payment = payments.pay(order.id(), method, order.total(), UUID.randomUUID().toString());
        } catch (SessionExpiredException e) {
            throw e;
        } catch (ApiException e) {
            throw new PaymentFailedException(order.id(), e);
        }
        if (cartToClear != null) {
            cartToClear.clear();
        }
        Order paid = orders.get(order.id());
        progress.accept("Generando el código de rastreo…");
        String code = TrackingCode.forOrder(paid);
        boolean started = false;
        try {
            JsonNode t = tracking.open(paid.id());
            code = t.path("code").asText(code);
            started = true;
        } catch (ApiException e) {
            // la compra ya está hecha; el rastreo se puede abrir después desde «Mis compras»
        }
        return new Result(paid, payment, code, started);
    }
}
