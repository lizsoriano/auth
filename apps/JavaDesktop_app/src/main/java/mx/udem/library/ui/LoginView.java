package mx.udem.library.ui;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.control.TextField;
import javafx.scene.control.TitledPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import mx.udem.library.api.ApiException;
import mx.udem.library.config.ServiceUrls;
import mx.udem.library.model.User;

import java.io.IOException;
import java.util.function.Consumer;

/**
 * Pantalla de inicio de sesión (Módulo 1): correo y contraseña se envían al microservicio Login, que devuelve el JWT.
 * Abajo, un panel plegable con UNA sola dirección: la del API Gateway (cada servicio es una ruta de esa dirección).
 */
public final class LoginView extends HBox {

    private final AppContext ctx;
    private final TextField email = new TextField();
    private final PasswordField password = new PasswordField();
    private final Label status = Ui.wrapped("", "muted");
    private final TextField gateway = new TextField();
    private final javafx.scene.control.Button loginButton = Ui.button("Iniciar sesión", "primary");

    public LoginView(AppContext ctx, Consumer<User> onLoggedIn) {
        this.ctx = ctx;
        getStyleClass().add("page");
        setPadding(Insets.EMPTY);

        VBox brand = new VBox(14, Ui.label("Library", "login-title"),
                Ui.wrapped("Catálogo, cesta de compras, pedidos y rastreo en tiempo real de tu entrega por Monterrey.", "login-text"),
                Ui.wrapped("Cliente de escritorio de los microservicios del proyecto: autenticación con JWT, REST + JSON y WebSockets.", "login-text"));
        brand.setPadding(new Insets(60, 40, 40, 50));
        brand.setAlignment(Pos.CENTER_LEFT);
        brand.getStyleClass().add("login-left");
        brand.setPrefWidth(430);
        brand.setMinWidth(380);

        email.setPromptText("correo@ejemplo.com");
        password.setPromptText("Contraseña");
        password.setOnAction(e -> submit(onLoggedIn));
        email.setOnAction(e -> password.requestFocus());
        loginButton.setDefaultButton(true);
        loginButton.setMaxWidth(Double.MAX_VALUE);
        loginButton.setOnAction(e -> submit(onLoggedIn));

        VBox form = new VBox(10, Ui.title("Iniciar sesión"), Ui.label("Usa tu cuenta de Library.", "subtitle"),
                Ui.label("Correo electrónico", "bold", "small"), email, Ui.label("Contraseña", "bold", "small"), password,
                loginButton, status, connectionPane());
        form.setMaxWidth(400);
        form.setPadding(new Insets(10));
        StackPane right = new StackPane(form);
        right.setPadding(new Insets(30));
        HBox.setHgrow(right, Priority.ALWAYS);
        getChildren().addAll(brand, right);
    }

    private TitledPane connectionPane() {
        gateway.setPromptText("http://localhost:8080 o la IP de la instancia");
        var thisPc = Ui.button("Esta computadora", "flat");
        thisPc.setOnAction(e -> gateway.setText(ServiceUrls.DEFAULT_GATEWAY));
        VBox box = new VBox(8, Ui.label("Dirección del gateway", "small", "muted"), gateway, thisPc,
                Ui.wrapped("Una sola dirección: cada servicio es una ruta de ella (/api/login, /api/books, /api/users, /api/authors, /api/pedidos, "
                        + "/api/pagos y /api/gps; el monolito, en /). En la instancia de GCP basta la IP, por ejemplo 34.51.109.238.", "small", "muted"),
                Ui.wrapped("Aquí no se guarda ninguna contraseña ni token.", "small", "muted"));
        TitledPane pane = new TitledPane("Conexión con los servicios", box);
        pane.setExpanded(false);
        // Las direcciones guardadas por versiones anteriores (un puerto por servicio) se muestran como la del gateway local.
        String saved = ctx.store.load().gatewayBase();
        gateway.setText(saved.isBlank() ? ServiceUrls.DEFAULT_GATEWAY : saved);
        return pane;
    }

    private ServiceUrls chosenUrls() {
        return ServiceUrls.gateway(gateway.getText());
    }

    private void submit(Consumer<User> onLoggedIn) {
        if (email.getText().isBlank() || password.getText().isEmpty()) {
            status.setText("Escribe tu correo y tu contraseña.");
            status.getStyleClass().setAll("label", "error-text");
            return;
        }
        ServiceUrls urls = chosenUrls();
        ctx.connect(urls);
        loginButton.setDisable(true);
        status.setText("Verificando tus credenciales…");
        status.getStyleClass().setAll("label", "muted");
        String mail = email.getText().trim();
        String pass = password.getText();
        Async.run(() -> ctx.backend().auth().login(mail, pass), user -> {
            password.clear();
            try {
                ctx.store.save(urls);
            } catch (IOException ignored) {
                // no poder guardar la configuración no impide usar la app
            }
            loginButton.setDisable(false);
            onLoggedIn.accept(user);
        }, error -> {
            loginButton.setDisable(false);
            String message = error instanceof ApiException api ? api.getMessage() : String.valueOf(error.getMessage());
            if (error instanceof ApiException api && api.status() == 401) {
                message = "Correo o contraseña incorrectos.";
            }
            status.setText(message);
            status.getStyleClass().setAll("label", "error-text");
            password.requestFocus();
        });
    }

    /** Para el modo de demostración: llena y envía el formulario sin teclear. */
    public void fillAndSubmit(String mail, String pass, Consumer<User> onLoggedIn) {
        email.setText(mail);
        password.setText(pass);
        submit(onLoggedIn);
    }
}
