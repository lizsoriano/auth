package mx.udem.library.ui;

import com.fasterxml.jackson.databind.JsonNode;
import javafx.application.Platform;
import javafx.concurrent.Worker;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.ComboBox;
import javafx.scene.control.Label;
import javafx.scene.control.ProgressBar;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.SplitPane;
import javafx.scene.control.TextField;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import javafx.scene.web.WebEngine;
import javafx.scene.web.WebView;
import mx.udem.library.api.Json;
import mx.udem.library.model.Order;
import mx.udem.library.model.TrackingCode;
import mx.udem.library.tracking.TrackingClient;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * Rastreo de pedidos (Módulo 6). El usuario escribe o elige un código; la aplicación abre el WebSocket (Java), manda su
 * JWT y, si el servidor confirma que el pedido es suyo, recibe la ruta y la posición del vehículo cada segundo. El mapa
 * (Leaflet + OpenStreetMap) vive en un {@link WebView} y Java le empuja cada mensaje; el panel de la derecha muestra el
 * estado, la ubicación y la línea de tiempo.
 */
public final class TrackingView extends VBox implements ShellView.Refreshable {

    private static final List<String> STEPS = List.of("confirmado", "preparando", "enviado", "en_ruta", "entregado");

    private final AppContext ctx;
    private final TextField code = new TextField();
    private final ComboBox<Order> myOrders = new ComboBox<>();
    private final Label connection = Ui.chip("desconectado");
    private final Label problem = Ui.wrapped("", "error-text", "small");
    private final WebView web = new WebView();
    private final WebEngine engine = web.getEngine();
    private final List<String> pendingJs = new ArrayList<>();
    private boolean pageLoaded;
    private TrackingClient client;
    private String activeCode = "";

    // panel derecho
    private final Label statusText = Ui.label("Sin seguimiento activo", "big-number");
    private final VBox timeline = new VBox(10);
    private final ProgressBar progress = new ProgressBar(0);
    private final Label progressText = Ui.label("0 %", "bold");
    private final Label where = Ui.wrapped("—", "");
    private final Label coords = Ui.label("—", "muted", "small");
    private final Label destination = Ui.wrapped("—", "");
    private final Label eta = Ui.wrapped("", "muted", "small");

    public TrackingView(AppContext ctx) {
        super(12);
        this.ctx = ctx;
        code.setPromptText("LIB-MTY-2026-000125");
        code.setPrefWidth(250);
        code.setOnAction(e -> start(code.getText()));
        myOrders.setPromptText("Mis pedidos rastreables");
        myOrders.setPrefWidth(300);
        myOrders.setCellFactory(l -> new javafx.scene.control.ListCell<>() {
            @Override
            protected void updateItem(Order o, boolean empty) {
                super.updateItem(o, empty);
                setText(empty || o == null ? null : label(o));
            }
        });
        myOrders.setButtonCell(new javafx.scene.control.ListCell<>() {
            @Override
            protected void updateItem(Order o, boolean empty) {
                super.updateItem(o, empty);
                setText(empty || o == null ? "Mis pedidos rastreables" : label(o));
            }
        });
        myOrders.setOnAction(e -> {
            Order o = myOrders.getValue();
            if (o != null) {
                code.setText(o.trackingCode());
            }
        });
        var track = Ui.button("Rastrear pedido", "primary");
        track.setOnAction(e -> start(code.getText()));
        var again = Ui.button("Volver a consultar");
        again.setOnAction(e -> consultAgain());
        var stop = Ui.button("Detener");
        stop.setOnAction(e -> stop());

        connection.setMinWidth(javafx.scene.layout.Region.USE_PREF_SIZE);
        track.setMinWidth(javafx.scene.layout.Region.USE_PREF_SIZE);
        again.setMinWidth(javafx.scene.layout.Region.USE_PREF_SIZE);
        stop.setMinWidth(javafx.scene.layout.Region.USE_PREF_SIZE);
        javafx.scene.layout.FlowPane bar = new javafx.scene.layout.FlowPane(10, 8, Ui.label("Código de rastreo", "bold"), code, myOrders, track, again, stop, connection);
        bar.setAlignment(Pos.CENTER_LEFT);
        bar.setRowValignment(javafx.geometry.VPos.CENTER);

        engine.setUserAgent("LibraryDesktop/1.0 (JavaFX WebView; rastreo de pedidos)");
        engine.getLoadWorker().stateProperty().addListener((o, a, state) -> {
            if (state == Worker.State.SUCCEEDED) {
                pageLoaded = true;
                pendingJs.forEach(this::runJs);
                pendingJs.clear();
            }
        });
        try {
            String html = new String(TrackingView.class.getResourceAsStream("/tracking-map.html").readAllBytes(), StandardCharsets.UTF_8);
            engine.loadContent(html);
        } catch (IOException e) {
            problem.setText("No se pudo cargar el mapa: " + e.getMessage());
        }

        VBox panel = new VBox(14, Ui.label("Estado del pedido", "section-title"), statusText, timeline,
                Ui.label("Avance de la ruta", "section-title"), new HBox(10, progress, progressText),
                Ui.label("Ubicación actual", "section-title"), where, coords,
                Ui.label("Entrega en", "section-title"), destination, eta, problem);
        progress.setPrefWidth(170);
        progressText.setMinWidth(javafx.scene.layout.Region.USE_PREF_SIZE);
        panel.setPadding(new Insets(16));
        panel.setPrefWidth(320);
        ScrollPane panelScroll = new ScrollPane(panel);
        panelScroll.setFitToWidth(true);
        panelScroll.getStyleClass().add("card");
        SplitPane split = new SplitPane(web, panelScroll);
        split.setDividerPositions(0.7);
        VBox.setVgrow(split, Priority.ALWAYS);

        getChildren().addAll(Ui.title("Rastrear pedido"),
                Ui.label("Escribe el código de tu compra o elige uno de tus pedidos pagados. La posición llega por WebSocket.", "subtitle"), bar, split);
        showTimeline("", List.of());
        ctx.backend().session().onNewToken(token -> {
            if (client != null) {
                client.refreshToken(token);
            }
        });
    }

    private static String label(Order o) {
        return o.trackingCode() + "  ·  pedido #" + o.id();
    }

    @Override
    public void refresh() {
        Async.run(() -> ctx.backend().orders().list(100), orders -> {
            Order selected = myOrders.getValue();
            myOrders.getItems().setAll(orders.stream().filter(Order::trackable).toList());
            if (selected != null) {
                myOrders.getItems().stream().filter(o -> o.id() == selected.id()).findFirst().ifPresent(myOrders::setValue);
            }
        }, err -> { });
    }

    /** Empieza a seguir un código (desde «Mis compras», desde la confirmación de compra o escrito a mano). */
    public void start(String typed) {
        String normalized = TrackingCode.normalize(typed);
        if (normalized.isEmpty()) {
            problem.setText("El código debe tener el formato LIB-MTY-2026-000125.");
            return;
        }
        stop();
        code.setText(normalized);
        problem.setText("");
        activeCode = normalized;
        resetPanel();
        client = new TrackingClient(ctx.backend().urls().trackingWsUrl(), () -> {
            ctx.backend().http().ensureFresh();
            return ctx.backend().session().accessToken();
        }, new TrackingClient.Listener() {
            @Override
            public void onState(TrackingClient.State state) {
                Platform.runLater(() -> setConnection(state));
            }

            @Override
            public void onMessage(JsonNode message) {
                Platform.runLater(() -> handle(message));
            }

            @Override
            public void onError(String errorCode, String message, boolean fatal) {
                Platform.runLater(() -> {
                    problem.setText(message);
                    if (fatal && "token_expired".equals(errorCode)) {
                        ctx.handleError(new mx.udem.library.api.SessionExpiredException("Tu sesión expiró. Inicia sesión de nuevo."));
                    }
                });
            }
        });
        // Mantiene el JWT vigente antes de conectar (la conexión lo manda en su primer mensaje).
        Async.quiet(() -> {
            ctx.backend().http().ensureFresh();
            client.connect(normalized);
        });
    }

    /** «El cliente podrá consultar nuevamente el seguimiento mediante su código»: lectura REST de su estado actual. */
    private void consultAgain() {
        String typed = TrackingCode.normalize(code.getText());
        if (typed.isEmpty()) {
            problem.setText("Escribe un código válido para consultarlo.");
            return;
        }
        problem.setText("");
        Async.run(() -> ctx.backend().tracking().byCode(typed), t -> {
            handle(withType(t, "snapshot"));
            problem.setText("Consulta por REST: " + t.path("status_text").asText() + " · " + Math.round(t.path("progress").asDouble() * 100) + " %");
            problem.getStyleClass().setAll("label", "muted", "small");
        }, err -> {
            problem.getStyleClass().setAll("label", "error-text", "small");
            problem.setText(err.getMessage());
            if (err instanceof mx.udem.library.api.SessionExpiredException) {
                ctx.handleError(err);
            }
        });
    }

    private static JsonNode withType(JsonNode t, String type) {
        return ((com.fasterxml.jackson.databind.node.ObjectNode) t.deepCopy()).put("type", type);
    }

    public void stop() {
        if (client != null) {
            client.shutdown();
            client = null;
        }
        setConnection(TrackingClient.State.CLOSED);
    }

    public String activeCode() {
        return activeCode;
    }

    private void setConnection(TrackingClient.State state) {
        String text = switch (state) {
            case CONNECTING -> "conectando";
            case CONNECTED -> "conectado";
            case RECONNECTING -> "reconectando";
            case CLOSED -> "desconectado";
        };
        connection.setText(text);
        connection.getStyleClass().setAll("label", "chip", "chip-" + text);
    }

    private void resetPanel() {
        statusText.setText("Conectando…");
        progress.setProgress(0);
        progressText.setText("0 %");
        where.setText("—");
        coords.setText("—");
        destination.setText("—");
        eta.setText("");
        showTimeline("", List.of());
        runJs("LibMap.apply({type:'reset'})");
    }

    private volatile String lastStatus = "";
    private volatile double lastProgress;

    /** Último estado recibido ({@code confirmado … entregado}); para el modo de demostración y las pruebas. */
    public String lastStatus() {
        return lastStatus;
    }

    public double lastProgress() {
        return lastProgress;
    }

    private void handle(JsonNode msg) {
        String type = msg.path("type").asText();
        if (!"snapshot".equals(type) && !"update".equals(type)) {
            return;
        }
        lastStatus = msg.path("status").asText();
        lastProgress = msg.path("progress").asDouble();
        problem.setText("");
        runJs("LibMap.apply(" + js(msg) + ")");
        String status = msg.path("status").asText();
        statusText.setText(msg.path("status_text").asText());
        double p = msg.path("progress").asDouble();
        progress.setProgress(p);
        progressText.setText(Math.round(p * 100) + " %");
        JsonNode pos = msg.path("position");
        where.setText(pos.path("street").asText("—").isBlank() ? "—" : pos.path("street").asText());
        coords.setText(String.format("%.5f, %.5f · %.0f km/h", pos.path("latitude").asDouble(), pos.path("longitude").asDouble(),
                pos.path("speed").asDouble()));
        JsonNode dest = msg.path("destination");
        if (!dest.isMissingNode()) {
            destination.setText(dest.path("name").asText() + "\nRuta: " + msg.path("route_name").asText() + " · "
                    + String.format("%.1f km", msg.path("route_distance_m").asDouble() / 1000));
        }
        if (msg.path("delivered").asBoolean()) {
            eta.setText("Entregado: el vehículo llegó al final de la ruta.");
        } else {
            long sim = msg.path("eta_sim_s").asLong();
            eta.setText("Tiempo restante simulado ≈ " + (sim / 60) + " min (el recorrido va " + Math.round(msg.path("time_scale").asDouble()) + "× más rápido)");
        }
        JsonNode tl = msg.path("timeline");
        if (tl.isArray() && !tl.isEmpty()) {
            List<String[]> rows = new ArrayList<>();
            tl.forEach(t -> rows.add(new String[]{t.path("status").asText(), t.path("text").asText(), t.path("reached").asBoolean() ? "1" : "0", Ui.date(t.path("at").asText())}));
            showTimeline(status, rows);
        } else if (!timeline.getChildren().isEmpty()) {
            updateCurrent(status);
        }
    }

    private List<String[]> lastRows = List.of();

    private void showTimeline(String status, List<String[]> rows) {
        lastRows = rows;
        timeline.getChildren().clear();
        List<String[]> shown = rows.isEmpty() ? STEPS.stream().map(s -> new String[]{s, labelOf(s), "0", ""}).toList() : rows;
        for (String[] row : shown) {
            boolean reached = "1".equals(row[2]);
            boolean current = reached && row[0].equals(status);
            Label dot = Ui.label(reached ? "✓" : "", "step-dot", current ? "step-current" : reached ? "step-done" : "step-todo");
            Label text = Ui.label(row[1], reached ? "bold" : "muted");
            HBox line = new HBox(10, dot, text);
            line.setAlignment(Pos.CENTER_LEFT);
            timeline.getChildren().add(line);
        }
    }

    private void updateCurrent(String status) {
        List<String[]> rows = new ArrayList<>();
        int idx = STEPS.indexOf(status);
        for (String[] r : lastRows) {
            rows.add(new String[]{r[0], r[1], STEPS.indexOf(r[0]) <= idx ? "1" : "0", r[3]});
        }
        showTimeline(status, rows);
    }

    private static String labelOf(String status) {
        return switch (status) {
            case "confirmado" -> "Pedido confirmado";
            case "preparando" -> "Preparando pedido";
            case "enviado" -> "Pedido enviado";
            case "en_ruta" -> "En ruta de entrega";
            default -> "Entregado";
        };
    }

    /** JSON → literal JavaScript seguro (se escapan los separadores de línea Unicode). */
    private static String js(JsonNode msg) {
        return Json.write(msg).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029");
    }

    private void runJs(String script) {
        if (!pageLoaded) {
            pendingJs.add(script);
            return;
        }
        try {
            engine.executeScript("if (typeof LibMap !== 'undefined') { " + script + " }");
        } catch (RuntimeException e) {
            problem.setText("No se pudo actualizar el mapa: " + e.getMessage());
        }
    }

    /** Para el modo de demostración y las pruebas. */
    public WebView web() {
        return web;
    }
}
