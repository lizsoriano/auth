package mx.udem.library.ui;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.ButtonType;
import javafx.scene.control.Dialog;
import javafx.scene.control.Label;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.Spinner;
import javafx.scene.layout.GridPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import mx.udem.library.model.Author;
import mx.udem.library.model.Book;

import java.util.List;

/** Detalle de un libro: portada, datos, descripción, autores con su biografía y botón para agregarlo a la cesta. */
final class BookDetailDialog {

    private BookDetailDialog() {
    }

    static void show(AppContext ctx, Book book, List<Author> authors) {
        Dialog<Void> dialog = new Dialog<>();
        dialog.initOwner(ctx.stage);
        dialog.setTitle("Library");
        dialog.setHeaderText(null);
        dialog.getDialogPane().getStylesheets().add(Ui.stylesheet());
        dialog.getDialogPane().getButtonTypes().add(ButtonType.CLOSE);

        GridPane facts = new GridPane();
        facts.setHgap(14);
        facts.setVgap(6);
        String[][] rows = {{"ISBN", book.isbn()}, {"Categoría", book.category()}, {"Año de publicación", book.publicationYear() > 0 ? String.valueOf(book.publicationYear()) : "—"},
                {"Disponibilidad", book.available() ? book.stock() + " ejemplares" : "Agotado"}};
        for (int i = 0; i < rows.length; i++) {
            facts.add(Ui.label(rows[i][0], "muted", "small"), 0, i);
            facts.add(Ui.label(rows[i][1], "bold"), 1, i);
        }

        VBox authorBox = new VBox(6);
        if (authors.isEmpty()) {
            authorBox.getChildren().add(Ui.wrapped(book.authorsText().isBlank() ? "Sin autores registrados." : book.authorsText(), "muted"));
        }
        for (Author a : authors) {
            authorBox.getChildren().add(Ui.label(a.fullName() + (a.booksCount() > 0 ? "  ·  " + a.booksCount() + " libro(s)" : ""), "bold"));
            if (!a.biography().isBlank()) {
                authorBox.getChildren().add(Ui.wrapped(a.biography(), "muted", "small"));
            }
        }

        Spinner<Integer> qty = new Spinner<>(1, Math.max(1, book.stock()), 1);
        qty.setEditable(false);
        qty.setPrefWidth(90);
        var add = Ui.button("Agregar a la cesta", "primary");
        add.setDisable(!book.available());
        add.setOnAction(e -> {
            int added = ctx.cart.add(book, qty.getValue());
            if (added == 0) {
                Dialogs.info(ctx.stage, "Cesta", "Ya tienes todos los ejemplares disponibles en la cesta.");
            } else {
                dialog.close();
            }
        });

        Label description = Ui.wrapped(book.description(authors), "");
        description.setMaxWidth(380);
        VBox right = new VBox(10, Ui.wrapped(book.title(), "page-title"), Ui.label(Ui.money(book.price()), "price"), facts,
                Ui.label("Descripción", "section-title"), description, Ui.label(authors.size() > 1 ? "Autores" : "Autor", "section-title"), authorBox,
                new HBox(10, Ui.label("Cantidad", "muted"), qty, add));
        ((HBox) right.getChildren().get(right.getChildren().size() - 1)).setAlignment(Pos.CENTER_LEFT);
        right.setPrefWidth(400);
        ScrollPane scroll = new ScrollPane(right);
        scroll.setFitToWidth(true);
        scroll.setPrefHeight(520);
        scroll.setPrefWidth(420);
        HBox layout = new HBox(22, CatalogView.cover(ctx, book.coverPath(), 200, 290), scroll);
        layout.setPadding(new Insets(10));
        dialog.getDialogPane().setContent(layout);
        dialog.showAndWait();
    }
}
