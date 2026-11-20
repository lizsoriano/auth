package mx.udem.library.api;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.HttpApi.Service;
import mx.udem.library.model.User;

import java.util.Map;

/** Microservicio Login: {@code POST /login}, {@code POST /logout}. */
public final class AuthApi {

    private final HttpApi http;

    public AuthApi(HttpApi http) {
        this.http = http;
    }

    /** Envía correo y contraseña al servicio de autenticación y guarda el JWT y el refresh token en la sesión. */
    public User login(String email, String password) {
        JsonNode data = http.call(Service.AUTH, "POST", "/login", null, Map.of("email", email, "password", password), null, false).body();
        http.session().setTokens(data);
        User user = User.from(data.path("user"));
        http.session().user(user);
        return user;
    }

    /** Cierra la sesión en el servidor (revoca el JWT) y limpia la sesión local pase lo que pase. */
    public void logout() {
        try {
            http.call(Service.AUTH, "POST", "/logout", null, null, null, true);
        } catch (ApiException ignored) {
            // si el servidor no responde o la sesión ya había vencido, igual se cierra localmente
        } finally {
            http.session().clear();
        }
    }
}
