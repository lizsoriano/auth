package mx.udem.library.ui;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Label;
import javafx.scene.control.ScrollPane;
import javafx.scene.control.TextField;
import javafx.scene.image.Image;
import javafx.scene.image.ImageView;
import javafx.scene.layout.FlowPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import mx.udem.library.model.Author;
import mx.udem.library.model.Book;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Catálogo (Módulo 2): libros de Books con portada, título, autores, precio y disponibilidad. Los autores y su
 * biografía salen del servicio Authors. La búsqueda por título filtra la lista ya cargada.
 */
public final class CatalogView extends VBox implements ShellView.Refreshable {

    private record Data(List<Book> books, Map<String, List<Author>> authors) {
    }

    private final AppContext ctx;
    private final TextField search = new TextField();
    private final FlowPane grid = new FlowPane(16, 16);
    private final Label info = Ui.label("", "subtitle");
    private Data data;
    private boolean loading;

    public CatalogView(AppContext ctx) {
        super(14);
        this.ctx = ctx;
        search.setPromptText("Buscar por título…");
        search.setPrefWidth(300);
        search.textProperty().addListener((o, a, b) -> render());
        var reload = Ui.button("Actualizar");
        reload.setOnAction(e -> load());
        HBox header = new HBox(14, new VBox(2, Ui.title("Catálogo"), info), Ui.spacer(), search, reload);
        header.setAlignment(Pos.CENTER_LEFT);

        grid.setPadding(new Insets(4, 4, 20, 4));
        ScrollPane scroll = new ScrollPane(grid);
        scroll.setFitToWidth(true);
        VBox.setVgrow(scroll, Priority.ALWAYS);
        getChildren().addAll(header, scroll);
    }

    @Override
    public void refresh() {
        if (data == null) {
            load();
        }
    }

    private void load() {
        if (loading) {
            return;
        }
        loading = true;
        info.setText("Cargando catálogo…");
        Async.run(() -> {
            List<Book> books = ctx.backend().books().catalog();
            Map<String, List<Author>> byIsbn = Map.of();
            try {
                List<Author> authors = ctx.backend().authors().list(100);
                byIsbn = ctx.backend().authors().byIsbn(authors);
            } catch (mx.udem.library.api.ApiException e) {
                if (e instanceof mx.udem.library.api.SessionExpiredException) {
                    throw e;
                }
                // sin el servicio Authors el catálogo igual se muestra, con el texto de autores de Books
            }
            return new Data(books, byIsbn);
        }, result -> {
            loading = false;
            data = result;
            render();
        }, error -> {
            loading = false;
            info.setText("No se pudo cargar el catálogo.");
            ctx.handleError(error);
        });
    }

    private void render() {
        if (data == null) {
            return;
        }
        String q = search.getText() == null ? "" : search.getText().trim().toLowerCase(Locale.ROOT);
        List<Book> shown = new ArrayList<>();
        data.books().stream().filter(b -> q.isEmpty() || b.title().toLowerCase(Locale.ROOT).contains(q)).forEach(shown::add);
        grid.getChildren().clear();
        shown.forEach(b -> grid.getChildren().add(card(b)));
        info.setText(shown.size() + " de " + data.books().size() + " libros");
        if (shown.isEmpty()) {
            grid.getChildren().add(Ui.label(q.isEmpty() ? "El catálogo está vacío." : "Ningún título coincide con «" + search.getText() + "».", "subtitle"));
        }
    }

    private VBox card(Book book) {
        List<Author> authors = data.authors().getOrDefault(book.isbn(), List.of());
        String names = authors.isEmpty() ? (book.authorsText().isBlank() ? "Autor no registrado" : book.authorsText())
                : String.join(", ", authors.stream().map(Author::fullName).toList());
        Label title = Ui.wrapped(book.title(), "bold");
        title.setMinHeight(40);
        title.setMaxWidth(200);
        Label author = Ui.wrapped(names, "muted", "small");
        author.setMaxWidth(200);
        Label stock = Ui.chip(book.available() ? "disponible" : "agotado");
        stock.setText(book.available() ? "Disponible · " + book.stock() : "Agotado");
        var details = Ui.button("Detalles");
        var add = Ui.button("Agregar", "primary");
        add.setDisable(!book.available());
        details.setOnAction(e -> BookDetailDialog.show(ctx, book, authors));
        add.setOnAction(e -> {
            if (ctx.cart.add(book, 1) == 0) {
                Dialogs.info(ctx.stage, "Cesta", "Ya tienes en la cesta todos los ejemplares disponibles de «" + book.title() + "».");
            }
        });
        HBox buttons = new HBox(8, details, add);
        VBox box = new VBox(8, cover(ctx, book.coverPath(), 150, 210), title, author, new HBox(8, Ui.label(Ui.money(book.price()), "price"), Ui.spacer(), stock), buttons);
        box.getStyleClass().add("book-card");
        box.setPadding(new Insets(14));
        box.setPrefWidth(228);
        box.setMaxWidth(228);
        box.setOnMouseClicked(e -> {
            if (e.getClickCount() == 2) {
                BookDetailDialog.show(ctx, book, authors);
            }
        });
        return box;
    }

    /** Portada del libro; si no hay imagen o no carga, se muestra «Portada no disponible». */
    static StackPane cover(AppContext ctx, String coverPath, double w, double h) {
        StackPane pane = new StackPane();
        pane.getStyleClass().add("cover");
        pane.setPrefSize(w, h);
        pane.setMinSize(w, h);
        pane.setMaxSize(w, h);
        Label missing = Ui.wrapped("Portada\nno disponible", "cover-missing");
        missing.setAlignment(Pos.CENTER);
        pane.getChildren().add(missing);
        String url = ctx.backend().urls().imageUrl(coverPath);
        if (url != null) {
            Image image = new Image(url, w, h, true, true, true);
            ImageView view = new ImageView(image);
            view.setPreserveRatio(true);
            view.setFitWidth(w);
            view.setFitHeight(h);
            image.errorProperty().addListener((o, a, failed) -> {
                if (failed) {
                    pane.getChildren().setAll(missing);
                }
            });
            image.progressProperty().addListener((o, a, p) -> {
                if (p.doubleValue() >= 1.0 && !image.isError()) {
                    pane.getChildren().setAll(view);
                }
            });
        }
        return pane;
    }
}
