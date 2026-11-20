package mx.udem.library.ui;

import javafx.beans.property.SimpleObjectProperty;
import javafx.beans.property.SimpleStringProperty;
import javafx.geometry.Pos;
import javafx.scene.control.Label;
import javafx.scene.control.Spinner;
import javafx.scene.control.TableCell;
import javafx.scene.control.TableColumn;
import javafx.scene.control.TableView;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import mx.udem.library.model.CartLine;

/** Cesta de compras (Módulo 3): cantidades, precios, subtotal y total, y el paso a «Confirmar compra». */
public final class CartView extends VBox implements ShellView.Refreshable {

    private final AppContext ctx;
    private final TableView<CartLine> table = new TableView<>();
    private final Label units = Ui.label("", "big-number");
    private final Label subtotal = Ui.label("", "muted");
    private final Label total = Ui.label("", "big-number");
    private final javafx.scene.control.Button confirm = Ui.button("Confirmar compra", "primary");
    private final javafx.scene.control.Button clear = Ui.button("Vaciar cesta", "danger");

    @SuppressWarnings("unchecked")
    public CartView(AppContext ctx) {
        super(14);
        this.ctx = ctx;

        TableColumn<CartLine, String> title = new TableColumn<>("Libro");
        title.setCellValueFactory(c -> new SimpleStringProperty(c.getValue().book().title()));
        title.setPrefWidth(300);
        TableColumn<CartLine, String> price = new TableColumn<>("Precio");
        price.setCellValueFactory(c -> new SimpleStringProperty(Ui.money(c.getValue().book().price())));
        price.setPrefWidth(110);
        TableColumn<CartLine, CartLine> qty = new TableColumn<>("Cantidad");
        qty.setCellValueFactory(c -> new SimpleObjectProperty<>(c.getValue()));
        qty.setCellFactory(col -> new TableCell<>() {
            @Override
            protected void updateItem(CartLine line, boolean empty) {
                super.updateItem(line, empty);
                if (empty || line == null) {
                    setGraphic(null);
                    return;
                }
                Spinner<Integer> spinner = new Spinner<>(1, Math.max(1, line.book().stock()), line.quantity());
                spinner.setPrefWidth(90);
                spinner.valueProperty().addListener((o, a, b) -> {
                    if (b != null && b != line.quantity()) {
                        ctx.cart.setQuantity(line.book().isbn(), b);
                    }
                });
                setGraphic(spinner);
            }
        });
        qty.setPrefWidth(120);
        TableColumn<CartLine, String> sub = new TableColumn<>("Subtotal");
        sub.setCellValueFactory(c -> new SimpleStringProperty(Ui.money(c.getValue().subtotal())));
        sub.setPrefWidth(120);
        TableColumn<CartLine, CartLine> remove = new TableColumn<>("");
        remove.setCellValueFactory(c -> new SimpleObjectProperty<>(c.getValue()));
        remove.setCellFactory(col -> new TableCell<>() {
            @Override
            protected void updateItem(CartLine line, boolean empty) {
                super.updateItem(line, empty);
                if (empty || line == null) {
                    setGraphic(null);
                    return;
                }
                var b = Ui.button("Quitar", "flat", "danger");
                b.setOnAction(e -> ctx.cart.remove(line.book().isbn()));
                setGraphic(b);
            }
        });
        remove.setPrefWidth(100);
        table.getColumns().addAll(title, price, qty, sub, remove);
        table.setPlaceholder(Ui.label("Tu cesta está vacía. Agrega libros desde el catálogo.", "subtitle"));
        table.setColumnResizePolicy(TableView.CONSTRAINED_RESIZE_POLICY_FLEX_LAST_COLUMN);
        VBox.setVgrow(table, Priority.ALWAYS);

        confirm.setMaxWidth(Double.MAX_VALUE);
        confirm.setOnAction(e -> new CheckoutFlow(ctx).start());
        clear.setOnAction(e -> {
            if (Dialogs.confirm(ctx.stage, "Vaciar la cesta", "Se quitarán todos los libros de la cesta.", "Vaciar")) {
                ctx.cart.clear();
            }
        });
        VBox summary = Ui.card(Ui.label("Resumen", "section-title"), new HBox(Ui.label("Artículos", "muted"), Ui.spacer(), units),
                new HBox(Ui.label("Subtotal", "muted"), Ui.spacer(), subtotal), new HBox(Ui.label("Total", "bold"), Ui.spacer(), total),
                Ui.wrapped("Compra simulada: no se pide ningún dato bancario. Antes de pagar se validan los precios y el stock con el servicio de libros.", "muted", "small"),
                confirm, clear);
        summary.setPrefWidth(290);
        summary.setMinWidth(290);
        summary.setAlignment(Pos.TOP_LEFT);

        HBox body = new HBox(16, table, summary);
        HBox.setHgrow(table, Priority.ALWAYS);
        VBox.setVgrow(body, Priority.ALWAYS);
        getChildren().addAll(Ui.title("Mi cesta"), Ui.label("Revisa tus libros, ajusta las cantidades y confirma la compra.", "subtitle"), body);
        ctx.cart.onChange(() -> Ui.fx(this::refresh));
        refresh();
    }

    @Override
    public void refresh() {
        table.getItems().setAll(ctx.cart.lines());
        units.setText(String.valueOf(ctx.cart.units()));
        subtotal.setText(Ui.money(ctx.cart.subtotal()));
        total.setText(Ui.money(ctx.cart.total()));
        confirm.setDisable(ctx.cart.isEmpty());
        clear.setDisable(ctx.cart.isEmpty());
    }
}
