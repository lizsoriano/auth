package mx.udem.library.model;

import java.math.BigDecimal;

/** Una línea de la cesta: un libro y cuántos ejemplares. */
public final class CartLine {

    private Book book;
    private int quantity;

    public CartLine(Book book, int quantity) {
        this.book = book;
        this.quantity = quantity;
    }

    public Book book() {
        return book;
    }

    public void book(Book fresh) {
        this.book = fresh;
    }

    public int quantity() {
        return quantity;
    }

    public void quantity(int quantity) {
        this.quantity = quantity;
    }

    public BigDecimal subtotal() {
        return book.price().multiply(BigDecimal.valueOf(quantity));
    }
}
