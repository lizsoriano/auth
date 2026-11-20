package mx.udem.library.api;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.HttpApi.Service;
import mx.udem.library.model.User;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Microservicio Users: perfil propio ({@code GET /users/me}) y, solo para administradores, el listado de usuarios. */
public final class UsersApi {

    private final HttpApi http;

    public UsersApi(HttpApi http) {
        this.http = http;
    }

    public User me() {
        return User.from(http.get(Service.USERS, "/users/me").path("user"));
    }

    /** {@code GET /users}: el servicio responde 403 a quien no es administrador. */
    public List<User> list(int limit) {
        JsonNode data = http.get(Service.USERS, "/users", Map.of("limit", String.valueOf(limit)));
        List<User> users = new ArrayList<>();
        data.path("users").forEach(u -> users.add(User.from(u)));
        return users;
    }
}
