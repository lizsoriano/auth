package mx.udem.library.model;

import com.fasterxml.jackson.databind.JsonNode;
import mx.udem.library.api.Json;

public record Author(long id, String firstName, String lastName, String biography, int booksCount) {

    public static Author from(JsonNode n) {
        return new Author(n.path("author_id").asLong(), Json.text(n, "first_name"), Json.text(n, "last_name"),
                Json.text(n, "biography"), n.path("books_count").asInt());
    }

    public String fullName() {
        return (firstName + " " + lastName).trim();
    }
}
