package mx.udem.library.ui;

import javafx.scene.control.Alert;
import javafx.scene.control.ButtonType;
import javafx.scene.control.Label;
import javafx.stage.Window;

import java.util.Optional;

/** Cuadros de diálogo con el estilo de la aplicación. */
public final class Dialogs {

    private Dialogs() {
    }

    public static void error(Window owner, String title, String message) {
        show(owner, Alert.AlertType.ERROR, title, message);
    }

    public static void info(Window owner, String title, String message) {
        show(owner, Alert.AlertType.INFORMATION, title, message);
    }

    public static void warning(Window owner, String title, String message) {
        show(owner, Alert.AlertType.WARNING, title, message);
    }

    public static boolean confirm(Window owner, String title, String message, String okText) {
        Alert alert = build(owner, Alert.AlertType.CONFIRMATION, title, message);
        ((javafx.scene.control.Button) alert.getDialogPane().lookupButton(ButtonType.OK)).setText(okText);
        ((javafx.scene.control.Button) alert.getDialogPane().lookupButton(ButtonType.CANCEL)).setText("Cancelar");
        Optional<ButtonType> result = alert.showAndWait();
        return result.isPresent() && result.get() == ButtonType.OK;
    }

    private static void show(Window owner, Alert.AlertType type, String title, String message) {
        build(owner, type, title, message).showAndWait();
    }

    private static Alert build(Window owner, Alert.AlertType type, String title, String message) {
        Alert alert = new Alert(type);
        if (owner != null) {
            alert.initOwner(owner);
        }
        alert.setTitle("Library");
        alert.setHeaderText(title);
        Label content = new Label(message);
        content.setWrapText(true);
        content.setMaxWidth(440);
        alert.getDialogPane().setContent(content);
        alert.getDialogPane().getStylesheets().add(Ui.stylesheet());
        return alert;
    }
}
