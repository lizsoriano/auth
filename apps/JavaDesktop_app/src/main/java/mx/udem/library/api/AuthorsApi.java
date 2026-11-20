package mx.udem.library.api;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.HttpApi.Service;
import mx.udem.library.model.Author;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/** Microservicio Authors (lecturas públicas): autores, su biografía y los libros de cada uno. */
public final class AuthorsApi {

    private final HttpApi http;

    public AuthorsApi(HttpApi http) {
        this.http = http;
    }

    public List<Author> list(int limit) {
        List<Author> authors = new ArrayList<>();
        http.get(Service.AUTHORS, "/authors", Map.of("limit", String.valueOf(limit))).path("authors")
                .forEach(a -> authors.add(Author.from(a)));
        return authors;
    }

    /** ISBN de los libros de un autor ({@code GET /authors/{id}/books}). */
    public List<String> isbnsOf(long authorId) {
        List<String> isbns = new ArrayList<>();
        JsonNode books = http.get(Service.AUTHORS, "/authors/" + authorId + "/books").path("books");
        books.forEach(b -> isbns.add(Json.text(b, "isbn")));
        return isbns;
    }

    /**
     * Relación ISBN → autores. El servicio no ofrece «autores de un libro», así que se consulta los libros de cada
     * autor (en paralelo) y se invierte. Los autores sin libros no se consultan.
     */
    public Map<String, List<Author>> byIsbn(List<Author> authors) {
        Map<String, List<Author>> result = new HashMap<>();
        List<CompletableFuture<Void>> jobs = new ArrayList<>();
        for (Author author : authors) {
            if (author.booksCount() == 0) {
                continue;
            }
            jobs.add(CompletableFuture.runAsync(() -> {
                try {
                    List<String> isbns = isbnsOf(author.id());
                    synchronized (result) {
                        isbns.forEach(i -> result.computeIfAbsent(i, k -> new ArrayList<>()).add(author));
                    }
                } catch (ApiException ignored) {
                    // un autor que falla no debe impedir mostrar el catálogo
                }
            }));
        }
        jobs.forEach(CompletableFuture::join);
        return result;
    }
}
