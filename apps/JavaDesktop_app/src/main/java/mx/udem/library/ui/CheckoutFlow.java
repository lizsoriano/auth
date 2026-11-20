package mx.udem.library.ui;

import javafx.application.Platform;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.ButtonType;
import javafx.scene.control.Dialog;
import javafx.scene.control.Label;
import javafx.scene.control.ProgressIndicator;
import javafx.scene.control.RadioButton;
import javafx.scene.control.ToggleGroup;
import javafx.scene.input.Clipboard;
import javafx.scene.input.ClipboardContent;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import mx.udem.library.api.PaymentFailedException;
import mx.udem.library.api.PaymentsApi;
import mx.udem.library.cart.PurchaseService;
import mx.udem.library.model.Order;

import java.math.BigDecimal;

/**
 * Compra simulada (Módulo 4): validar la cesta contra Books, elegir el método de pago (simulado), crear el pedido en
 * Pedidos, pagarlo en Pagos y mostrar la confirmación con el código de rastreo.
 */
final class CheckoutFlow {

    private final AppContext ctx;

    CheckoutFlow(AppContext ctx) {
        this.ctx = ctx;
    }

    /** Desde la cesta: valida, pregunta el método y crea el pedido. */
    void start() {
        Async.run(ctx, () -> ctx.purchases().validate(ctx.cart), validation -> {
            if (!validation.ok()) {
                Dialogs.warning(ctx.stage, "Revisa tu cesta", String.join("\n", validation.issues())
                        + "\n\nActualicé la cesta con los datos vigentes; revísala y confirma de nuevo.");
                return;
            }
            String method = askMethod("Confirmar compra", ctx.cart.units() + " artículo(s)", ctx.cart.total());
            if (method == null) {
                return;
            }
            runWithProgress("Procesando tu compra", progress -> ctx.purchases().checkout(ctx.cart, method, progress));
        });
    }

    /** Desde «Mis compras»: paga un pedido que quedó pendiente. */
    void payPending(Order order, Runnable afterwards) {
        String method = askMethod("Pagar pedido #" + order.id(), order.units() + " artículo(s)", order.total());
        if (method == null) {
            return;
        }
        runWithProgress("Registrando tu pago", progress -> ctx.purchases().pay(order, method, progress, null));
        if (afterwards != null) {
            afterwards.run();
        }
    }

    private String askMethod(String title, String detail, BigDecimal total) {
        Dialog<String> dialog = new Dialog<>();
        dialog.initOwner(ctx.stage);
        dialog.setTitle("Library");
        dialog.setHeaderText(title);
        dialog.getDialogPane().getStylesheets().add(Ui.stylesheet());
        ToggleGroup group = new ToggleGroup();
        VBox methods = new VBox(8);
        for (String m : PaymentsApi.METHODS) {
            RadioButton r = new RadioButton(Character.toUpperCase(m.charAt(0)) + m.substring(1));
            r.setUserData(m);
            r.setToggleGroup(group);
            methods.getChildren().add(r);
            if (m.equals("tarjeta")) {
                r.setSelected(true);
            }
        }
        Label note = Ui.wrapped("Pago simulado: el servicio Pagos solo registra el método y el monto. No escribas ni se solicitan datos bancarios.", "muted", "small");
        note.setMaxWidth(360);
        VBox box = new VBox(12, new HBox(10, Ui.label(detail, "muted"), Ui.spacer(), Ui.label(Ui.money(total), "price")),
                Ui.label("Método de pago", "section-title"), methods, note);
        box.setPadding(new Insets(6));
        box.setPrefWidth(380);
        dialog.getDialogPane().setContent(box);
        ButtonType pay = new ButtonType("Pagar (simulado)", javafx.scene.control.ButtonBar.ButtonData.OK_DONE);
        dialog.getDialogPane().getButtonTypes().addAll(pay, ButtonType.CANCEL);
        dialog.setResultConverter(b -> b == pay ? (String) group.getSelectedToggle().getUserData() : null);
        return dialog.showAndWait().orElse(null);
    }

    private interface Work {
        PurchaseService.Result run(java.util.function.Consumer<String> progress);
    }

    private void runWithProgress(String title, Work work) {
        Label step = Ui.label("Iniciando…", "muted");
        ProgressIndicator spinner = new ProgressIndicator();
        spinner.setPrefSize(48, 48);
        VBox box = new VBox(14, spinner, step);
        box.setAlignment(Pos.CENTER);
        box.setPadding(new Insets(20, 40, 20, 40));
        Dialog<Void> wait = new Dialog<>();
        wait.initOwner(ctx.stage);
        wait.setTitle("Library");
        wait.setHeaderText(title);
        wait.getDialogPane().getStylesheets().add(Ui.stylesheet());
        wait.getDialogPane().setContent(box);
        wait.getDialogPane().getButtonTypes().add(ButtonType.CLOSE);
        wait.getDialogPane().lookupButton(ButtonType.CLOSE).setVisible(false);
        wait.getDialogPane().lookupButton(ButtonType.CLOSE).setManaged(false);
        wait.show();
        Async.run(() -> work.run(text -> Platform.runLater(() -> step.setText(text))), result -> {
            forceClose(wait);
            showConfirmation(result);
        }, error -> {
            forceClose(wait);
            if (error instanceof PaymentFailedException failed) {
                Dialogs.warning(ctx.stage, "Pago no completado", failed.getMessage());
            } else {
                ctx.handleError(error);
            }
        });
    }

    private static void forceClose(Dialog<?> dialog) {
        dialog.getDialogPane().getButtonTypes().setAll(ButtonType.CLOSE);
        dialog.close();
    }

    private void showConfirmation(PurchaseService.Result result) {
        Dialog<Void> dialog = new Dialog<>();
        dialog.initOwner(ctx.stage);
        dialog.setTitle("Library");
        dialog.setHeaderText("¡Compra realizada!");
        dialog.getDialogPane().getStylesheets().add(Ui.stylesheet());
        Label code = Ui.label(result.trackingCode(), "big-number");
        var copy = Ui.button("Copiar código");
        copy.setOnAction(e -> {
            ClipboardContent content = new ClipboardContent();
            content.putString(result.trackingCode());
            Clipboard.getSystemClipboard().setContent(content);
            copy.setText("Copiado ✓");
        });
        var track = Ui.button("Rastrear pedido", "primary");
        track.setOnAction(e -> {
            dialog.close();
            ctx.nav().track(result.trackingCode());
        });
        VBox box = new VBox(10,
                new HBox(8, Ui.label("Pedido", "muted"), Ui.label("#" + result.order().id(), "bold"), Ui.chip(result.order().status())),
                new HBox(8, Ui.label("Total", "muted"), Ui.label(Ui.money(result.order().total()), "bold")),
                new HBox(8, Ui.label("Pago", "muted"), Ui.label(result.payment().method() + " · ", "bold"), Ui.chip(result.payment().status())),
                Ui.label("Código de rastreo", "section-title"), code,
                Ui.wrapped(result.trackingStarted()
                        ? "Con este código puedes seguir la entrega en el mapa, en tiempo real."
                        : "El servidor de rastreo no respondió todavía. El código es válido: podrás rastrear el pedido más tarde desde «Mis compras».", "muted"),
                new HBox(10, copy, track));
        box.setPadding(new Insets(6));
        box.setPrefWidth(420);
        dialog.getDialogPane().setContent(box);
        dialog.getDialogPane().getButtonTypes().add(ButtonType.CLOSE);
        dialog.showAndWait();
        ctx.nav().go(AppContext.Section.ORDERS);
    }
}
