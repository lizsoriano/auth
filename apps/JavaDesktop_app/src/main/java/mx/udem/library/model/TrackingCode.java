package mx.udem.library.model;

import java.time.Year;
import java.util.OptionalLong;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Código de rastreo: {@code LIB-MTY-2026-000125}. El servidor lo valida contra el pedido real; esto solo da formato. */
public final class TrackingCode {

    private static final Pattern FORMAT = Pattern.compile("^LIB-MTY-(\\d{4})-(\\d{6})$");

    private TrackingCode() {
    }

    public static String forOrder(Order order) {
        return format(yearOf(order.createdAt()), order.id());
    }

    public static String format(int year, long orderId) {
        return String.format("LIB-MTY-%04d-%06d", year, orderId);
    }

    /** Normaliza lo que escribe el usuario (espacios, minúsculas) y devuelve vacío si no tiene el formato. */
    public static String normalize(String typed) {
        if (typed == null) {
            return "";
        }
        String code = typed.trim().toUpperCase();
        return FORMAT.matcher(code).matches() ? code : "";
    }

    public static OptionalLong orderId(String code) {
        Matcher m = FORMAT.matcher(code == null ? "" : code.trim().toUpperCase());
        return m.matches() ? OptionalLong.of(Long.parseLong(m.group(2))) : OptionalLong.empty();
    }

    private static int yearOf(String isoDate) {
        if (isoDate != null && isoDate.length() >= 4 && isoDate.substring(0, 4).chars().allMatch(Character::isDigit)) {
            return Integer.parseInt(isoDate.substring(0, 4));
        }
        return Year.now().getValue();
    }
}
