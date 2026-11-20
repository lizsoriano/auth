package mx.udem.library.model;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.Json;

/** Usuario autenticado. Login y Users nombran algunos campos distinto ({@code id}/{@code user_id}, {@code role}/{@code role_name}). */
public record User(long id, String email, String displayName, String nombre, String apellidoPaterno,
                   String apellidoMaterno, int roleId, String role) {

    public static final int ROLE_ADMIN = 1;
    public static final int ROLE_STAFF = 2;
    public static final int ROLE_CUSTOMER = 3;

    public static User from(JsonNode n) {
        long id = n.hasNonNull("user_id") ? n.get("user_id").asLong() : n.path("id").asLong();
        String role = n.hasNonNull("role_name") ? n.get("role_name").asText() : Json.text(n, "role");
        String nombre = Json.text(n, "nombre");
        String display = Json.text(n, "display_name", nombre.isBlank() ? Json.text(n, "email") : nombre);
        return new User(id, Json.text(n, "email"), display, nombre, Json.text(n, "apellido_paterno"),
                Json.text(n, "apellido_materno"), n.path("role_id").asInt(ROLE_CUSTOMER), role);
    }

    public boolean isPrivileged() {
        return roleId == ROLE_ADMIN || roleId == ROLE_STAFF;
    }

    public String fullName() {
        String full = (nombre + " " + apellidoPaterno + " " + apellidoMaterno).trim().replaceAll("\\s+", " ");
        return full.isBlank() ? displayName : full;
    }
}
