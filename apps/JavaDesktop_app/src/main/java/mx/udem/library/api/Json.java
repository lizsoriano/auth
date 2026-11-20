package mx.udem.library.api;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.math.BigDecimal;
import java.math.RoundingMode;

/** Utilidades de JSON compartidas (Jackson) y lectura tolerante de campos. */
public final class Json {

    public static final ObjectMapper MAPPER = new ObjectMapper();

    private Json() {
    }

    public static JsonNode parse(String text) {
        try {
            return MAPPER.readTree(text);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException("JSON inválido: " + e.getOriginalMessage(), e);
        }
    }

    public static String write(Object value) {
        try {
            return MAPPER.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException(e);
        }
    }

    /** Dinero con dos decimales; los servicios lo mandan como número o como texto. */
    public static BigDecimal money(JsonNode node) {
        if (node == null || node.isNull() || node.isMissingNode()) {
            return BigDecimal.ZERO.setScale(2);
        }
        BigDecimal value = node.isNumber() ? node.decimalValue() : new BigDecimal(node.asText("0").trim());
        return value.setScale(2, RoundingMode.HALF_UP);
    }

    public static String text(JsonNode node, String field) {
        JsonNode v = node.path(field);
        return v.isMissingNode() || v.isNull() ? "" : v.asText();
    }

    public static String text(JsonNode node, String field, String fallback) {
        String v = text(node, field);
        return v.isBlank() ? fallback : v;
    }
}
