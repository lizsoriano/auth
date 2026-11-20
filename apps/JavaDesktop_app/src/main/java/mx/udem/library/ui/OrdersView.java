package mx.udem.library.ui;

import javafx.beans.property.SimpleStringProperty;
import javafx.geometry.Insets;
import javafx.scene.control.Label;
import javafx.scene.control.SplitPane;
import javafx.scene.control.TableColumn;
import javafx.scene.control.TableView;
import javafx.scene.input.Clipboard;
import javafx.scene.input.ClipboardContent;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import mx.udem.library.model.Order;
import mx.udem.library.model.Payment;

import java.util.List;

/**
 * Mis compras (Módulo 5): pedidos del usuario (Pedidos), sus libros, el total, el estado de la compra y del pago (Pagos)
 * y el código de rastreo. Nada se inventa: el estado «pagado» solo aparece si el servicio Pedidos lo reporta.
 */
public final class OrdersView extends VBox implements ShellView.Refreshable {

    private final AppContext ctx;
    private final TableView<Order> table = new TableView<>();
    private final VBox detail = new VBox(12);
    private final Label info = Ui.label("", "subtitle");

    @SuppressWarnings("unchecked")
    public OrdersView(AppContext ctx) {
        super(14);
        this.ctx = ctx;
        TableColumn<Order, String> id = new TableColumn<>("Pedido");
        id.setCellValueFactory(c -> new SimpleStringProperty("#" + c.getValue().id()));
        id.setPrefWidth(80);
        TableColumn<Order, String> date = new TableColumn<>("Fecha");
        date.setCellValueFactory(c -> new SimpleStringProperty(Ui.date(c.getValue().createdAt())));
        date.setPrefWidth(140);
        TableColumn<Order, String> total = new TableColumn<>("Total");
        total.setCellValueFactory(c -> new SimpleStringProperty(Ui.money(c.getValue().total())));
        total.setPrefWidth(100);
        TableColumn<Order, String> status = new TableColumn<>("Estado");
        status.setCellValueFactory(c -> new SimpleStringProperty(c.getValue().status()));
        status.setCellFactory(col -> new javafx.scene.control.TableCell<>() {
            @Override
            protected void updateItem(String s, boolean empty) {
                super.updateItem(s, empty);
                setGraphic(empty || s == null ? null : Ui.chip(s));
                setText(null);
            }
        });
        status.setPrefWidth(110);
        table.getColumns().addAll(id, date, total, status);
        table.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY_FLEX_LAST_COLUMN);
        table.setPlaceholder(Ui.label("Aún no tienes compras.", "subtitle"));
        table.getSelectionModel().selectedItemProperty().addListener((o, a, order) -> showDetail(order));

        var reload = Ui.button("Actualizar");
        reload.setOnAction(e -> refresh());
        HBox header = new HBox(14, new VBox(2, Ui.title("Mis compras"), info), Ui.spacer(), reload);

        detail.setPadding(new Insets(4, 0, 0, 16));
        SplitPane split = new SplitPane(table, detail);
        split.setDividerPositions(0.46);
        VBox.setVgrow(split, Priority.ALWAYS);
        showDetail(null);
        getChildren().addAll(header, split);
    }

    @Override
    public void refresh() {
        Order selected = table.getSelectionModel().getSelectedItem();
        info.setText("Cargando…");
        Async.run(ctx, () -> ctx.backend().orders().list(100), orders -> {
            table.getItems().setAll(orders);
            info.setText(orders.size() + " pedido(s)");
            if (selected != null) {
                orders.stream().filter(o -> o.id() == selected.id()).findFirst().ifPresent(o -> table.getSelectionModel().select(o));
            } else if (!orders.isEmpty()) {
                table.getSelectionModel().selectFirst();
            }
        });
    }

    /** El listado de Pedidos no trae las líneas: al elegir un pedido se pide su detalle ({@code GET /pedidos/{id}}). */
    private void showDetail(Order summary) {
        detail.getChildren().clear();
        if (summary == null) {
            detail.getChildren().add(Ui.label("Selecciona un pedido para ver sus detalles.", "subtitle"));
            return;
        }
        detail.getChildren().add(Ui.label("Cargando el pedido #" + summary.id() + "…", "subtitle"));
        Async.run(() -> ctx.backend().orders().get(summary.id()), full -> {
            if (table.getSelectionModel().getSelectedItem() != null && table.getSelectionModel().getSelectedItem().id() == full.id()) {
                renderDetail(full);
            }
        }, err -> {
            detail.getChildren().setAll(Ui.label("No se pudo cargar el pedido.", "error-text"));
            if (err instanceof mx.udem.library.api.SessionExpiredException) {
                ctx.handleError(err);
            }
        });
    }

    private void renderDetail(Order order) {
        detail.getChildren().clear();
        TableView<Order.Item> items = new TableView<>();
        TableColumn<Order.Item, String> title = new TableColumn<>("Libro");
        title.setCellValueFactory(c -> new SimpleStringProperty(c.getValue().title()));
        TableColumn<Order.Item, String> qty = new TableColumn<>("Cant.");
        qty.setCellValueFactory(c -> new SimpleStringProperty(String.valueOf(c.getValue().quantity())));
        qty.setPrefWidth(60);
        TableColumn<Order.Item, String> price = new TableColumn<>("Precio");
        price.setCellValueFactory(c -> new SimpleStringProperty(Ui.money(c.getValue().unitPrice())));
        price.setPrefWidth(95);
        TableColumn<Order.Item, String> sub = new TableColumn<>("Subtotal");
        sub.setCellValueFactory(c -> new SimpleStringProperty(Ui.money(c.getValue().subtotal())));
        sub.setPrefWidth(100);
        items.getColumns().addAll(List.of(title, qty, price, sub));
        items.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY_FLEX_LAST_COLUMN);
        items.getItems().setAll(order.items());
        items.setPrefHeight(34 + 32.0 * Math.max(1, order.items().size()));
        items.setMaxHeight(240);

        Label payment = Ui.label("Pago: consultando…", "muted");
        Async.run(() -> ctx.backend().payments().ofOrder(order.id()), payments -> {
            if (payments.isEmpty()) {
                payment.setText("Pago: sin pagos registrados.");
            } else {
                Payment p = payments.get(0);
                payment.setText("Pago: " + p.method() + " · " + p.status() + " · " + Ui.money(p.amount()) + " · " + Ui.date(p.createdAt()));
            }
        }, e -> payment.setText("Pago: no se pudo consultar."));

        HBox head = new HBox(10, Ui.label("Pedido #" + order.id(), "section-title"), Ui.chip(order.status()));
        detail.getChildren().addAll(head, Ui.label(Ui.date(order.createdAt()), "muted"), items,
                new HBox(8, Ui.label("Total", "muted"), Ui.label(Ui.money(order.total()), "price")), payment);

        if (order.trackable()) {
            Label code = Ui.label(order.trackingCode(), "big-number");
            var copy = Ui.button("Copiar");
            copy.setOnAction(e -> {
                ClipboardContent content = new ClipboardContent();
                content.putString(order.trackingCode());
                Clipboard.getSystemClipboard().setContent(content);
                copy.setText("Copiado ✓");
            });
            var track = Ui.button("Abrir seguimiento en el mapa", "primary");
            track.setOnAction(e -> ctx.nav().track(order.trackingCode()));
            detail.getChildren().addAll(Ui.label("Código de rastreo", "muted", "small"), new HBox(10, code, copy), track);
        } else if (order.pending()) {
            var pay = Ui.button("Pagar ahora (simulado)", "primary");
            pay.setOnAction(e -> new CheckoutFlow(ctx).payPending(order, null));
            var cancel = Ui.button("Cancelar pedido", "danger");
            cancel.setOnAction(e -> {
                if (Dialogs.confirm(ctx.stage, "Cancelar pedido #" + order.id(), "Se cancelará el pedido y se repondrá el stock.", "Cancelar pedido")) {
                    Async.run(ctx, () -> ctx.backend().orders().cancel(order.id()), o -> refresh());
                }
            });
            detail.getChildren().addAll(Ui.wrapped("Este pedido aún no está pagado: el rastreo empieza cuando se registra el pago.", "muted"), new HBox(10, pay, cancel));
        } else {
            detail.getChildren().add(Ui.wrapped("Este pedido está cancelado: no tiene entrega que rastrear.", "muted"));
        }
    }
}
