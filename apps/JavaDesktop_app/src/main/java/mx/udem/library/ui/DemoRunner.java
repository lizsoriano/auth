package mx.udem.library.ui;

import javafx.application.Platform;
import javafx.scene.Node;
import javafx.scene.image.PixelReader;
import javafx.scene.image.WritableImage;
import mx.udem.library.LibraryApp;
import mx.udem.library.cart.PurchaseService;
import mx.udem.library.model.Book;
import mx.udem.library.ui.AppContext.Section;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.function.Supplier;

/**
 * Recorrido automático para generar las evidencias: {@code -Dlibrary.demo.dir=<carpeta>} con las variables de entorno
 * {@code LIBRARY_DEMO_USER} y {@code LIBRARY_DEMO_PASSWORD} (nunca se escriben en el código ni en disco).
 *
 * <p>Usa las MISMAS clases que la interfaz (inicio de sesión, catálogo, cesta, {@link PurchaseService}, rastreo por
 * WebSocket) contra los servicios reales; solo la confirmación de la compra se dispara por código para no depender de
 * cuadros de diálogo modales. Guarda una captura por pantalla y un {@code demo_log.txt} con lo que ocurrió.
 */
public final class DemoRunner {

    private final AppContext ctx;
    private final LibraryApp app;
    private final Path dir;
    private final List<String> log = new ArrayList<>();

    private DemoRunner(AppContext ctx, LibraryApp app, Path dir) {
        this.ctx = ctx;
        this.app = app;
        this.dir = dir;
    }

    public static void maybeRun(AppContext ctx, LibraryApp app) {
        String dir = System.getProperty("library.demo.dir");
        if (dir == null || dir.isBlank()) {
            return;
        }
        Thread t = new Thread(() -> {
            DemoRunner runner = new DemoRunner(ctx, app, Path.of(dir));
            try {
                Files.createDirectories(runner.dir);
                runner.run();
            } catch (Throwable e) {
                runner.note("FALLÓ: " + e);
            } finally {
                runner.writeLog();
                Platform.runLater(Platform::exit);
                try {
                    Thread.sleep(800);
                } catch (InterruptedException ignored) {
                    // saliendo
                }
                System.exit(0);
            }
        }, "demo-runner");
        t.setDaemon(true);
        t.start();
    }

    private void run() throws Exception {
        String user = System.getenv("LIBRARY_DEMO_USER");
        String password = System.getenv("LIBRARY_DEMO_PASSWORD");
        if (user == null || password == null) {
            throw new IllegalStateException("Faltan LIBRARY_DEMO_USER y LIBRARY_DEMO_PASSWORD en el entorno.");
        }
        sleep(1500);
        LoginView login = fx(() -> (LoginView) ctx.stage.getScene().getRoot());
        shot("01_login", login);
        fx(() -> {
            login.fillAndSubmit(user, password, u -> app.showShell(u));
            return null;
        });
        waitFor(() -> app.shell() != null, 20_000, "inicio de sesión");
        note("Inicio de sesión correcto: JWT obtenido del servicio Login.");
        sleep(3500);
        shot("02_catalogo", fx(() -> app.shell()));

        List<Book> books = ctx.backend().books().catalog();
        note("Catálogo: " + books.size() + " libros desde Books.");
        List<Book> buyable = books.stream().filter(Book::available).limit(2).toList();
        fx(() -> {
            buyable.forEach(b -> ctx.cart.add(b, 1));
            if (!buyable.isEmpty()) {
                ctx.cart.add(buyable.get(0), 1);
            }
            app.shell().go(Section.CART);
            return null;
        });
        sleep(800);
        shot("03_cesta", fx(() -> app.shell()));

        PurchaseService.Validation validation = ctx.purchases().validate(ctx.cart);
        note("Validación de la cesta contra Books: " + (validation.ok() ? "precios y stock vigentes" : validation.issues()));
        PurchaseService.Result result = ctx.purchases().checkout(ctx.cart, "tarjeta", s -> note("  · " + s));
        note("Pedido #" + result.order().id() + " [" + result.order().status() + "], pago " + result.payment().status()
                + ", código de rastreo " + result.trackingCode() + (result.trackingStarted() ? "" : " (rastreo no iniciado)"));
        fx(() -> {
            app.shell().go(Section.ORDERS);
            return null;
        });
        sleep(2500);
        shot("04_mis_compras", fx(() -> app.shell()));

        fx(() -> {
            app.shell().track(result.trackingCode());
            return null;
        });
        TrackingView tracking = fx(() -> app.shell().tracking());
        String[] names = {"05_rastreo_preparando", "06_rastreo_en_ruta", "07_rastreo_a_mitad", "08_rastreo_entregado"};
        String[] status = {"preparando", "en_ruta", "en_ruta", "entregado"};
        double[] minProgress = {0, 0.15, 0.55, 1.0};
        for (int i = 0; i < names.length; i++) {
            int step = i;
            waitFor(() -> tracking.lastStatus().equals(status[step]) && tracking.lastProgress() >= minProgress[step], 150_000,
                    "rastreo: " + status[step] + " ≥ " + (int) (minProgress[step] * 100) + " %");
            // el WebView necesita unos segundos para bajar los tiles la primera vez; después ya están en caché y basta menos
            // (con 6 s en las capturas intermedias el recorrido ya habría terminado y la 07 saldría igual que la 08)
            sleep(i == 0 ? 6000 : 2000);
            shot(names[i], fx(() -> app.shell()));
            note("Rastreo recibido por WebSocket: " + tracking.lastStatus() + " · " + Math.round(tracking.lastProgress() * 100) + " % de la ruta");
            note("  mapa: " + fx(() -> String.valueOf(tracking.web().getEngine().executeScript(
                    "typeof L + ' ' + document.getElementById('map').clientWidth + 'x' + document.getElementById('map').clientHeight"
                            + " + ' tiles=' + document.querySelectorAll('.leaflet-tile-loaded').length + ' | ' + document.getElementById('banner').innerText.replace(/\\n/g,' ')"))));
        }

        fx(() -> {
            app.shell().go(Section.PROFILE);
            return null;
        });
        sleep(1500);
        shot("09_perfil", fx(() -> app.shell()));
        if (fx(() -> ctx.backend().session().user().isPrivileged())) {
            fx(() -> {
                app.shell().go(Section.ADMIN);
                return null;
            });
            sleep(2500);
            shot("09b_administracion", fx(() -> app.shell()));
            note("Administración visible solo para admin/staff (rol " + fx(() -> ctx.backend().session().user().role()) + ").");
        }
        fx(() -> {
            app.shell().go(Section.SOAP);
            return null;
        });
        sleep(600);
        shot("10_soap", fx(() -> app.shell()));
        note("Recorrido terminado.");
    }

    // ------------------------------------------------------------------ utilidades
    private <T> T fx(Supplier<T> work) throws Exception {
        if (Platform.isFxApplicationThread()) {
            return work.get();
        }
        CompletableFuture<T> future = new CompletableFuture<>();
        Platform.runLater(() -> {
            try {
                future.complete(work.get());
            } catch (Throwable e) {
                future.completeExceptionally(e);
            }
        });
        return future.get();
    }

    /**
     * Captura SOLO la escena de la aplicación (nunca la pantalla). El contenido del WebView se pide aparte
     * ({@code WebView.snapshot}) y se pega sobre su lugar, porque {@code Node.snapshot} de la raíz no siempre lo pinta.
     */
    private void shot(String name, Node node) throws Exception {
        fx(() -> {
            try {
                Node root = ctx.stage.getScene().getRoot();
                WritableImage image = root.snapshot(null, null);
                PixelReader reader = image.getPixelReader();
                int w = (int) image.getWidth();
                int h = (int) image.getHeight();
                BufferedImage out = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
                for (int y = 0; y < h; y++) {
                    for (int x = 0; x < w; x++) {
                        out.setRGB(x, y, reader.getArgb(x, y));
                    }
                }
                if (app.shell() != null && app.shell().current() == Section.TRACKING) {
                    javafx.scene.web.WebView web = app.shell().tracking().web();
                    WritableImage webImage = web.snapshot(null, null);
                    javafx.geometry.Bounds b = web.localToScene(web.getBoundsInLocal());
                    PixelReader wr = webImage.getPixelReader();
                    for (int y = 0; y < (int) webImage.getHeight(); y++) {
                        for (int x = 0; x < (int) webImage.getWidth(); x++) {
                            int px = (int) b.getMinX() + x;
                            int py = (int) b.getMinY() + y;
                            if (px >= 0 && py >= 0 && px < w && py < h) {
                                out.setRGB(px, py, wr.getArgb(x, y));
                            }
                        }
                    }
                }
                ImageIO.write(out, "png", dir.resolve(name + ".png").toFile());
            } catch (IOException e) {
                throw new IllegalStateException(e);
            }
            return null;
        });
        note("Captura guardada: " + name + ".png");
    }

    private void waitFor(Supplier<Boolean> condition, long millis, String what) throws Exception {
        long end = System.currentTimeMillis() + millis;
        while (System.currentTimeMillis() < end) {
            if (fx(condition)) {
                return;
            }
            sleep(200);
        }
        throw new IllegalStateException("Tiempo agotado esperando: " + what);
    }

    private static void sleep(long ms) throws InterruptedException {
        Thread.sleep(ms);
    }

    private void note(String text) {
        synchronized (log) {
            log.add(java.time.LocalTime.now().withNano(0) + "  " + text);
        }
    }

    private void writeLog() {
        try {
            Files.write(dir.resolve("demo_log.txt"), log, java.nio.charset.StandardCharsets.UTF_8);
        } catch (IOException ignored) {
            // sin bitácora no hay nada más que hacer
        }
    }
}
