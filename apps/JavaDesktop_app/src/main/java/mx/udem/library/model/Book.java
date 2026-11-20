package mx.udem.library.model;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.Json;

import java.math.BigDecimal;
import java.util.List;

/**
 * Libro del catálogo. {@code coverPath} es la ruta que devuelve {@code GET /books/images} (por ejemplo
 * {@code /uploads/seed/978…-1.jpg}); la imagen en sí la publica otro host, ver {@code ServiceUrls.imageUrl}.
 */
public record Book(long bookId, String isbn, String title, BigDecimal price, String category, int stock,
                   int publicationYear, String authorsText, String coverPath) {

    public static Book from(JsonNode n) {
        return new Book(n.path("bookId").asLong(), Json.text(n, "isbn"), Json.text(n, "title"), Json.money(n.get("price")),
                Json.text(n, "category"), n.path("stock").asInt(), n.path("publicationYear").asInt(),
                Json.text(n, "authors"), null);
    }

    public Book withCover(String path) {
        return new Book(bookId, isbn, title, price, category, stock, publicationYear, authorsText, path);
    }

    public boolean available() {
        return stock > 0;
    }

    /**
     * El servicio Books no tiene un campo «descripción»: se arma con los datos que sí publica (categoría, año, autores)
     * y, si el servicio Authors tiene la biografía del autor, se agrega. Es la adaptación mínima documentada en el README.
     */
    public String description(List<Author> authors) {
        StringBuilder sb = new StringBuilder();
        sb.append(title).append(" es un libro de la categoría ").append(category.isBlank() ? "general" : category);
        if (publicationYear > 0) {
            sb.append(", publicado en ").append(publicationYear);
        }
        sb.append('.');
        for (Author a : authors) {
            if (!a.biography().isBlank()) {
                sb.append("\n\nSobre ").append(a.fullName()).append(": ").append(a.biography());
            }
        }
        return sb.toString();
    }
}
