package mx.udem.library.api;

/**
 * Error al hablar con un microservicio. {@code status == 0} significa que no hubo respuesta (servidor apagado,
 * URL equivocada, firewall); cualquier otro valor es el código HTTP que el servidor sí devolvió.
 */
public class ApiException extends RuntimeException {

    private final int status;
    private final String code;

    public ApiException(int status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    public int status() {
        return status;
    }

    /** Código del contrato de errores de los servicios (p. ej. {@code order_not_paid}); puede ser {@code null}. */
    public String code() {
        return code;
    }

    public boolean isNetwork() {
        return status == 0;
    }
}
