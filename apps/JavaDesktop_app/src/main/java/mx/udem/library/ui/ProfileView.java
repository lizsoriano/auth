package mx.udem.library.ui;

import com.fasterxml.jackson.databind.JsonNode;
import javafx.scene.control.Label;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import mx.udem.library.model.User;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

/** Perfil del usuario (Módulo 1): datos del servicio Users y el estado de la sesión JWT. Nada se guarda en disco. */
public final class ProfileView extends VBox implements ShellView.Refreshable {

    private final AppContext ctx;
    private final GridPane profile = new GridPane();
    private final GridPane session = new GridPane();
    private final Label message = Ui.wrapped("", "muted");

    public ProfileView(AppContext ctx) {
        super(14);
        this.ctx = ctx;
        profile.setHgap(18);
        profile.setVgap(8);
        session.setHgap(18);
        session.setVgap(8);
        var renew = Ui.button("Renovar token ahora");
        renew.setOnAction(e -> Async.run(ctx, () -> ctx.backend().http().refreshTokens(), ok -> {
            message.setText(ok ? "El JWT se renovó con el refresh token (un solo uso: ya hay uno nuevo)." : "No se pudo renovar: inicia sesión de nuevo.");
            fillSession();
            if (!ok) {
                ctx.logoutLocal();
            }
        }));
        VBox me = Ui.card(Ui.label("Mi cuenta", "section-title"), profile);
        VBox jwt = Ui.card(Ui.label("Sesión y JWT", "section-title"), session,
                Ui.wrapped("El JWT (HS256, 20 minutos) viaja en la cabecera Authorization: Bearer de cada llamada protegida y se renueva solo antes de vencer. Vive únicamente en memoria.", "muted", "small"),
                new HBox(10, renew), message);
        me.setPrefWidth(430);
        jwt.setPrefWidth(430);
        getChildren().addAll(Ui.title("Mi perfil"), Ui.label("Datos del servicio Users y de tu sesión.", "subtitle"), new HBox(16, me, jwt));
        fillSession();
    }

    @Override
    public void refresh() {
        Async.run(ctx, () -> ctx.backend().users().me(), user -> {
            ctx.backend().session().user(user);
            fill(profile, new String[][]{{"Nombre", user.fullName()}, {"Correo", user.email()}, {"Identificador", String.valueOf(user.id())},
                    {"Rol", user.role() + " (id " + user.roleId() + ")"}});
        });
        fillSession();
    }

    private void fillSession() {
        JsonNode claims = ctx.backend().session().claims();
        User u = ctx.backend().session().user();
        String exp = claims.has("exp") ? DateTimeFormatter.ofPattern("HH:mm:ss").format(Instant.ofEpochSecond(claims.get("exp").asLong()).atZone(ZoneId.systemDefault())) : "—";
        long left = ctx.backend().session().secondsLeft();
        fill(session, new String[][]{{"Usuario autenticado", u == null ? "—" : u.displayName()}, {"user_id (claim)", claims.path("user_id").asText("—")},
                {"role_id (claim)", claims.path("role_id").asText("—")}, {"Emisor (iss)", claims.path("iss").asText("—")},
                {"Vence a las", exp + String.format("  (en %d:%02d)", left / 60, left % 60)}});
    }

    private static void fill(GridPane grid, String[][] rows) {
        grid.getChildren().clear();
        for (int i = 0; i < rows.length; i++) {
            grid.add(Ui.label(rows[i][0], "muted"), 0, i);
            grid.add(Ui.label(rows[i][1], "bold"), 1, i);
        }
    }
}
