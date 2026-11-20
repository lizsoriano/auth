package mx.udem.library.api;

/** El pedido se creó pero el pago no se pudo registrar: el pedido queda «pendiente» y se puede pagar después. */
public class PaymentFailedException extends ApiException {

    private final long orderId;

    public PaymentFailedException(long orderId, ApiException cause) {
        super(cause.status(), cause.code(), "El pedido #" + orderId + " quedó pendiente de pago: " + cause.getMessage()
                + "\nPuedes pagarlo desde «Mis compras».");
        this.orderId = orderId;
    }

    public long orderId() {
        return orderId;
    }
}
