package mx.udem.library.api;

/** El JWT venció o fue revocado y no se pudo renovar: hay que volver a autenticarse. */
public class SessionExpiredException extends ApiException {

    public SessionExpiredException(String message) {
        super(401, "session_expired", message);
    }
}
