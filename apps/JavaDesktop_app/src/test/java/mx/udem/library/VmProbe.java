package mx.udem.library;

import mx.udem.library.api.ApiException;
import mx.udem.library.api.Backend;
import mx.udem.library.config.ServiceUrls;
import mx.udem.library.model.Author;
import mx.udem.library.model.Book;

import java.util.List;

/**
 * Herramienta de evidencia (no es una prueba): usa las clases REALES de la app Java contra el reverse proxy de la instancia, sin iniciar
 * sesión: catálogo y autores (públicos) y un recurso protegido que debe responder 401 del servicio.
 * Uso: java ... mx.udem.library.VmProbe &lt;IP-o-dirección-del-gateway&gt;
 */
public final class VmProbe {

    public static void main(String[] args) {
        ServiceUrls urls = ServiceUrls.gateway(args[0]);
        System.out.println("Dirección única del gateway: " + urls.gatewayBase());
        System.out.println("  login    " + urls.auth());
        System.out.println("  books    " + urls.books());
        System.out.println("  authors  " + urls.authors());
        System.out.println("  pedidos  " + urls.pedidos());
        System.out.println("  rastreo  " + urls.tracking() + "   (WebSocket: " + urls.trackingWsUrl() + ")");
        System.out.println("  portadas " + urls.images());
        Backend backend = new Backend(urls);

        List<Book> books = backend.books().catalog();
        System.out.println("\nCatálogo por " + urls.books() + ": " + books.size() + " libros");
        for (Book b : books.stream().limit(5).toList()) {
            System.out.println("  - " + b.title() + " · $" + b.price() + " · stock " + b.stock() + " · portada: " + urls.imageUrl(b.coverPath()));
        }
        List<Author> authors = backend.authors().list(50);
        System.out.println("\nAutores por " + urls.authors() + ": " + authors.size());

        try {
            backend.orders().list(10);
            System.out.println("\nPedidos sin sesión: respondió (inesperado)");
        } catch (ApiException e) {
            System.out.println("\nPedidos sin iniciar sesión (recurso protegido por JWT): HTTP " + e.status() + " del servicio -> " + e.getMessage());
        } catch (RuntimeException e) {
            System.out.println("\nPedidos sin iniciar sesión (recurso protegido por JWT): " + e.getClass().getSimpleName() + " -> " + e.getMessage());
        }
    }
}
