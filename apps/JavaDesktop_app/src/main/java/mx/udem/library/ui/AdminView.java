package mx.udem.library.ui;

import javafx.beans.property.SimpleStringProperty;
import javafx.scene.control.Label;
import javafx.scene.control.Tab;
import javafx.scene.control.TabPane;
import javafx.scene.control.TableColumn;
import javafx.scene.control.TableView;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import mx.udem.library.api.ApiException;
import mx.udem.library.model.Order;
import mx.udem.library.model.User;

/**
 * Administración (solo admin y staff): usuarios y pedidos de todos. Los permisos los decide cada servicio: un staff
 * que pide la lista de usuarios recibe 403 y aquí se muestra tal cual, sin esconderlo.
 */
public final class AdminView extends VBox implements ShellView.Refreshable {

    private final AppContext ctx;
    private final TableView<User> users = new TableView<>();
    private final TableView<Order> orders = new TableView<>();
    private final Label usersNote = Ui.label("", "muted");
    private final Label ordersNote = Ui.label("", "muted");

    @SuppressWarnings("unchecked")
    public AdminView(AppContext ctx) {
        super(14);
        this.ctx = ctx;
        TableColumn<User, String> id = col("Id", 70, u -> String.valueOf(u.id()));
        users.getColumns().addAll(id, col("Nombre", 220, User::fullName), col("Correo", 260, User::email), col("Rol", 120, User::role));
        users.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY_FLEX_LAST_COLUMN);
        orders.getColumns().addAll(col("Pedido", 80, o -> "#" + o.id()), col("Usuario", 90, o -> String.valueOf(o.userId())),
                col("Fecha", 150, o -> Ui.date(o.createdAt())), col("Total", 110, o -> Ui.money(o.total())), col("Estado", 110, Order::status));
        orders.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY_FLEX_LAST_COLUMN);

        Tab usersTab = new Tab("Usuarios", new VBox(8, usersNote, users));
        Tab ordersTab = new Tab("Pedidos de todos", new VBox(8, ordersNote, orders));
        usersTab.setClosable(false);
        ordersTab.setClosable(false);
        VBox.setVgrow(users, Priority.ALWAYS);
        VBox.setVgrow(orders, Priority.ALWAYS);
        TabPane tabs = new TabPane(usersTab, ordersTab);
        VBox.setVgrow(tabs, Priority.ALWAYS);
        getChildren().addAll(Ui.title("Administración"), Ui.label("Solo para administradores y personal. Cada servicio verifica tu rol.", "subtitle"), tabs);
    }

    private static <T> TableColumn<T, String> col(String title, double width, java.util.function.Function<T, String> f) {
        TableColumn<T, String> c = new TableColumn<>(title);
        c.setCellValueFactory(x -> new SimpleStringProperty(f.apply(x.getValue())));
        c.setPrefWidth(width);
        return c;
    }

    @Override
    public void refresh() {
        Async.run(() -> ctx.backend().users().list(200), list -> {
            users.getItems().setAll(list);
            usersNote.setText(list.size() + " usuario(s)");
        }, err -> {
            users.getItems().clear();
            usersNote.setText(err instanceof ApiException api && api.status() == 403
                    ? "El servicio Users solo permite listar usuarios a un administrador (403)." : err.getMessage());
            if (err instanceof mx.udem.library.api.SessionExpiredException) {
                ctx.handleError(err);
            }
        });
        Async.run(() -> ctx.backend().orders().list(200), list -> {
            orders.getItems().setAll(list);
            ordersNote.setText(list.size() + " pedido(s) de todos los usuarios");
        }, err -> ordersNote.setText(err.getMessage()));
    }
}
