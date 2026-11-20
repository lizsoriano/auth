package mx.udem.library.ui;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.layout.Region;
import javafx.scene.layout.VBox;

import java.math.BigDecimal;
import java.text.NumberFormat;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/** Fábricas pequeñas de componentes y formatos (dinero, fechas) para que todas las vistas se vean igual. */
public final class Ui {

    private static final NumberFormat MONEY = NumberFormat.getCurrencyInstance(Locale.of("es", "MX"));
    private static final DateTimeFormatter DATE = DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm");

    private Ui() {
    }

    /** Ejecuta en el hilo de JavaFX (los cambios de la cesta pueden venir de un hilo de red). */
    public static void fx(Runnable work) {
        if (javafx.application.Platform.isFxApplicationThread()) {
            work.run();
        } else {
            javafx.application.Platform.runLater(work);
        }
    }

    public static String stylesheet() {
        return Ui.class.getResource("/style.css").toExternalForm();
    }

    public static String money(BigDecimal value) {
        return MONEY.format(value);
    }

    /** Fecha ISO del servidor ({@code 2026-11-06T21:01:40+00:00}) en hora local. */
    public static String date(String iso) {
        try {
            return OffsetDateTime.parse(iso).atZoneSameInstant(ZoneId.systemDefault()).format(DATE);
        } catch (RuntimeException e) {
            return iso == null ? "" : iso;
        }
    }

    public static Label label(String text, String... styleClasses) {
        Label l = new Label(text);
        l.getStyleClass().addAll(styleClasses);
        return l;
    }

    public static Label wrapped(String text, String... styleClasses) {
        Label l = label(text, styleClasses);
        l.setWrapText(true);
        return l;
    }

    public static Button button(String text, String... styleClasses) {
        Button b = new Button(text);
        b.getStyleClass().addAll(styleClasses);
        return b;
    }

    public static Label chip(String status) {
        Label l = label(status, "chip", "chip-" + status.toLowerCase().replace(' ', '-'));
        l.setAlignment(Pos.CENTER);
        return l;
    }

    public static VBox card(Node... children) {
        VBox box = new VBox(10, children);
        box.getStyleClass().add("card");
        box.setPadding(new Insets(16));
        return box;
    }

    public static Region spacer() {
        Region r = new Region();
        javafx.scene.layout.HBox.setHgrow(r, javafx.scene.layout.Priority.ALWAYS);
        VBox.setVgrow(r, javafx.scene.layout.Priority.ALWAYS);
        return r;
    }

    public static Label title(String text) {
        return label(text, "page-title");
    }
}
