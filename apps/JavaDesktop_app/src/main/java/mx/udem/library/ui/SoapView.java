package mx.udem.library.ui;

import javafx.scene.control.TextArea;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.VBox;
import mx.udem.library.api.SoapApi;

/** Integración demostrativa con SOAP/XML: se envía un sobre SOAP 1.1 al endpoint de Books y se muestra la respuesta. */
public final class SoapView extends VBox {

    private final TextArea request = new TextArea(SoapApi.REQUEST);
    private final TextArea response = new TextArea();

    public SoapView(AppContext ctx) {
        super(12);
        request.setStyle("-fx-font-family: Consolas, monospace; -fx-font-size: 13px;");
        response.setStyle("-fx-font-family: Consolas, monospace; -fx-font-size: 13px;");
        response.setEditable(false);
        response.setPromptText("La respuesta XML aparece aquí.");
        var send = Ui.button("Enviar solicitud SOAP", "primary");
        send.setOnAction(e -> {
            response.setText("Enviando…");
            Async.run(() -> ctx.backend().soap().send(request.getText()), response::setText, err -> {
                response.setText("Error: " + err.getMessage());
            });
        });
        HBox boxes = new HBox(14, new VBox(6, Ui.label("Solicitud (editable)", "section-title"), request),
                new VBox(6, Ui.label("Respuesta", "section-title"), response));
        HBox.setHgrow(boxes.getChildren().get(0), Priority.ALWAYS);
        HBox.setHgrow(boxes.getChildren().get(1), Priority.ALWAYS);
        VBox.setVgrow(request, Priority.ALWAYS);
        VBox.setVgrow(response, Priority.ALWAYS);
        VBox.setVgrow(boxes, Priority.ALWAYS);
        getChildren().addAll(Ui.title("SOAP / XML (demostración)"),
                Ui.wrapped("El servicio Books publica además un endpoint SOAP 1.1 document/literal (contrato en GET /wsdl). Aquí se llama a la operación "
                        + "ObtenerConceptosPendientes sin filtros. El comercio (pedidos y pagos) sigue siendo REST + JSON.", "subtitle"), send, boxes);
    }
}
