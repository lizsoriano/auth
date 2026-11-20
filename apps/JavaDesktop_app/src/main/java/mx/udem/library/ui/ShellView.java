package mx.udem.library.ui;

import javafx.animation.KeyFrame;
import javafx.animation.Timeline;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Label;
import javafx.scene.control.ToggleButton;
import javafx.scene.control.ToggleGroup;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import javafx.util.Duration;
import mx.udem.library.model.User;
import mx.udem.library.ui.AppContext.Section;

import java.util.EnumMap;
import java.util.Map;
import java.util.function.Supplier;

/** Ventana principal: barra lateral con las secciones y, al centro, la vista elegida (se crean al abrirlas la primera vez). */
public final class ShellView extends BorderPane implements AppContext.Navigator {

    private final AppContext ctx;
    private final StackPane content = new StackPane();
    private final Map<Section, Node> views = new EnumMap<>(Section.class);
    private final Map<Section, Supplier<Node>> factories = new EnumMap<>(Section.class);
    private final Map<Section, ToggleButton> buttons = new EnumMap<>(Section.class);
    private final ToggleGroup group = new ToggleGroup();
    private final Label sessionLabel = Ui.label("", "sidebar-note");
    private final Label cartBadge = Ui.label("0", "badge");
    private final TrackingView trackingView;
    private Section current;

    public ShellView(AppContext ctx) {
        this.ctx = ctx;
        ctx.nav(this);
        User user = ctx.backend().session().user();

        trackingView = new TrackingView(ctx);
        factories.put(Section.CATALOG, () -> new CatalogView(ctx));
        factories.put(Section.CART, () -> new CartView(ctx));
        factories.put(Section.ORDERS, () -> new OrdersView(ctx));
        factories.put(Section.TRACKING, () -> trackingView);
        factories.put(Section.PROFILE, () -> new ProfileView(ctx));
        factories.put(Section.ADMIN, () -> new AdminView(ctx));
        factories.put(Section.SOAP, () -> new SoapView(ctx));

        VBox nav = new VBox(6);
        nav.getChildren().addAll(navButton(Section.CATALOG, "Catálogo"), cartButton(), navButton(Section.ORDERS, "Mis compras"),
                navButton(Section.TRACKING, "Rastrear pedido"), navButton(Section.PROFILE, "Mi perfil"));
        if (user != null && user.isPrivileged()) {
            nav.getChildren().add(navButton(Section.ADMIN, "Administración"));
        }
        nav.getChildren().add(navButton(Section.SOAP, "SOAP (demostración)"));

        VBox userBox = new VBox(2, Ui.label(user == null ? "" : user.displayName(), "user-name"),
                Ui.label(user == null ? "" : roleName(user), "user-role"));
        userBox.getStyleClass().add("user-box");
        var logout = Ui.button("Cerrar sesión");
        logout.setMaxWidth(Double.MAX_VALUE);
        logout.setOnAction(e -> logout());

        VBox sidebar = new VBox(16, new VBox(0, Ui.label("Library", "brand"), Ui.label("Monterrey · cliente de escritorio", "brand-sub")),
                userBox, nav, Ui.spacer(), sessionLabel, logout);
        sidebar.getStyleClass().add("sidebar");
        sidebar.setPrefWidth(250);
        sidebar.setMinWidth(250);

        content.getStyleClass().add("page");
        setLeft(sidebar);
        setCenter(content);

        ctx.cart.onChange(() -> Ui.fx(this::updateBadge));
        updateBadge();
        startSessionClock();
        go(Section.CATALOG);
    }

    private static String roleName(User user) {
        return switch (user.roleId()) {
            case User.ROLE_ADMIN -> "Administrador";
            case User.ROLE_STAFF -> "Personal de la librería";
            default -> "Cliente";
        };
    }

    private ToggleButton navButton(Section section, String text) {
        ToggleButton b = new ToggleButton(text);
        b.getStyleClass().add("nav-button");
        b.setToggleGroup(group);
        b.setMaxWidth(Double.MAX_VALUE);
        b.setOnAction(e -> go(section));
        buttons.put(section, b);
        return b;
    }

    private Node cartButton() {
        ToggleButton b = navButton(Section.CART, "Mi cesta");
        HBox box = new HBox(b, cartBadge);
        box.setAlignment(Pos.CENTER_LEFT);
        HBox.setHgrow(b, javafx.scene.layout.Priority.ALWAYS);
        cartBadge.setPadding(new Insets(1, 8, 1, 8));
        box.setSpacing(-44);
        box.setPickOnBounds(false);
        cartBadge.setMouseTransparent(true);
        cartBadge.setTranslateX(-8);
        return box;
    }

    private void updateBadge() {
        int units = ctx.cart.units();
        cartBadge.setText(String.valueOf(units));
        cartBadge.setVisible(units > 0);
    }

    @Override
    public void go(Section section) {
        Node view = views.computeIfAbsent(section, s -> factories.get(s).get());
        content.getChildren().setAll(view);
        ToggleButton b = buttons.get(section);
        if (b != null) {
            b.setSelected(true);
        }
        current = section;
        if (view instanceof Refreshable r) {
            r.refresh();
        }
    }

    @Override
    public void track(String code) {
        go(Section.TRACKING);
        trackingView.start(code);
    }

    public Section current() {
        return current;
    }

    public TrackingView tracking() {
        return trackingView;
    }

    public Node view(Section section) {
        return views.computeIfAbsent(section, s -> factories.get(s).get());
    }

    private void logout() {
        trackingView.stop();
        Async.run(() -> {
            ctx.backend().auth().logout();
            return true;
        }, ok -> ctx.logoutLocal(), err -> ctx.logoutLocal());
    }

    /** Muestra cuánto le queda al JWT y lo renueva en segundo plano antes de que venza; si ya no se puede, vuelve al login. */
    private void startSessionClock() {
        int[] ticks = {0};
        Timeline clock = new Timeline(new KeyFrame(Duration.seconds(1), e -> {
            var session = ctx.backend().session();
            if (!session.active()) {
                return;
            }
            long left = session.secondsLeft();
            sessionLabel.setText(String.format("Sesión JWT · vence en %d:%02d", left / 60, left % 60));
            if (++ticks[0] % 15 == 0) {
                Async.quiet(() -> ctx.backend().http().ensureFresh());
            }
        }));
        clock.setCycleCount(Timeline.INDEFINITE);
        clock.play();
        sceneProperty().addListener((o, a, scene) -> {
            if (scene == null) {
                clock.stop();
            }
        });
    }

    /** Vistas que se recargan cada vez que se abren. */
    public interface Refreshable {
        void refresh();
    }
}
