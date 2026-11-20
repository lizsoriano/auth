package mx.udem.library.api;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.HttpApi.Service;
import mx.udem.library.model.Book;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Microservicio Books. El catálogo sale de dos llamadas públicas: {@code GET /books} (precio, stock, categoría…) y
 * {@code GET /books/images} (portadas), que se unen por ISBN.
 */
public final class BooksApi {

    private final HttpApi http;

    public BooksApi(HttpApi http) {
        this.http = http;
    }

    public List<Book> catalog() {
        Map<String, String> covers = new HashMap<>();
        try {
            for (JsonNode b : http.get(Service.BOOKS, "/books/images").path("books")) {
                String cover = null;
                for (JsonNode img : b.path("images")) {
                    if (cover == null || img.path("is_cover").asBoolean()) {
                        cover = img.path("url").asText(null);
                    }
                }
                covers.put(Json.text(b, "isbn"), cover);
            }
        } catch (ApiException e) {
            if (e.isNetwork()) {
                throw e;
            }
            // sin imágenes el catálogo sigue siendo válido: se muestra «portada no disponible»
        }
        List<Book> books = new ArrayList<>();
        for (JsonNode b : http.get(Service.BOOKS, "/books").path("books")) {
            Book book = Book.from(b);
            books.add(book.withCover(covers.get(book.isbn())));
        }
        return books;
    }

    /** {@code GET /books/{isbn}}: datos frescos (precio y stock vigentes) para validar la cesta antes de comprar. */
    public Book get(String isbn, String coverPath) {
        return Book.from(http.get(Service.BOOKS, "/books/" + isbn)).withCover(coverPath);
    }
}
