package mx.udem.library.cart;

import mx.udem.library.model.Book;
import mx.udem.library.model.CartLine;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Cesta de compras en memoria (se pierde al cerrar la app, como permite el enunciado). */
public final class Cart {

    private final Map<String, CartLine> lines = new LinkedHashMap<>();
    private final List<Runnable> listeners = new ArrayList<>();

    /** Agrega ejemplares sin pasar del stock. Devuelve cuántos se agregaron realmente (0 si ya está al tope). */
    public int add(Book book, int quantity) {
        if (quantity < 1) {
            return 0;
        }
        CartLine line = lines.get(book.isbn());
        int current = line == null ? 0 : line.quantity();
        int allowed = Math.max(0, Math.min(quantity, book.stock() - current));
        if (allowed == 0) {
            return 0;
        }
        if (line == null) {
            lines.put(book.isbn(), new CartLine(book, allowed));
        } else {
            line.quantity(current + allowed);
        }
        changed();
        return allowed;
    }

    /** Fija la cantidad de una línea (entre 1 y el stock). Una cantidad menor a 1 la elimina. */
    public void setQuantity(String isbn, int quantity) {
        CartLine line = lines.get(isbn);
        if (line == null) {
            return;
        }
        if (quantity < 1) {
            lines.remove(isbn);
        } else {
            line.quantity(Math.min(quantity, Math.max(1, line.book().stock())));
        }
        changed();
    }

    public void remove(String isbn) {
        if (lines.remove(isbn) != null) {
            changed();
        }
    }

    public void clear() {
        if (!lines.isEmpty()) {
            lines.clear();
            changed();
        }
    }

    /** Actualiza el libro de una línea con datos frescos del servicio (precio y stock vigentes). */
    public void refresh(Book fresh) {
        CartLine line = lines.get(fresh.isbn());
        if (line != null) {
            line.book(fresh);
            if (line.quantity() > fresh.stock()) {
                line.quantity(Math.max(1, fresh.stock()));
            }
            changed();
        }
    }

    public List<CartLine> lines() {
        return List.copyOf(lines.values());
    }

    public boolean isEmpty() {
        return lines.isEmpty();
    }

    public int units() {
        return lines.values().stream().mapToInt(CartLine::quantity).sum();
    }

    public BigDecimal subtotal() {
        return lines.values().stream().map(CartLine::subtotal).reduce(BigDecimal.ZERO, BigDecimal::add).setScale(2);
    }

    /** No hay impuestos ni envío en esta simulación: el total es el subtotal. */
    public BigDecimal total() {
        return subtotal();
    }

    public void onChange(Runnable listener) {
        listeners.add(listener);
    }

    private void changed() {
        listeners.forEach(Runnable::run);
    }
}
