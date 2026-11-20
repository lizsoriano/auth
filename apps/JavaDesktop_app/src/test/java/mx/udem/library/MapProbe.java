package mx.udem.library;

import javafx.application.Application;
import javafx.application.Platform;
import javafx.concurrent.Worker;
import javafx.scene.Scene;
import javafx.scene.image.PixelReader;
import javafx.scene.image.WritableImage;
import javafx.scene.web.WebView;
import javafx.stage.Stage;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Herramienta de diagnóstico (no es una prueba): carga solo tracking-map.html en un WebView, aplica un seguimiento real
 * guardado en un archivo y guarda una captura del WebView y cuántas teselas se cargaron.
 * Uso: java ... mx.udem.library.MapProbe &lt;snapshot.json&gt; &lt;salida.png&gt; [segundos]
 */
public final class MapProbe extends Application {

    @Override
    public void start(Stage stage) throws Exception {
        String[] a = getParameters().getRaw().toArray(new String[0]);
        String json = Files.readString(Path.of(a[0]), StandardCharsets.UTF_8);
        Path out = Path.of(a[1]);
        int seconds = a.length > 2 ? Integer.parseInt(a[2]) : 10;
        String html = new String(MapProbe.class.getResourceAsStream("/tracking-map.html").readAllBytes(), StandardCharsets.UTF_8);
        WebView web = new WebView();
        web.setPrefSize(820, 560);
        web.getEngine().setUserAgent("LibraryDesktop/1.0 (JavaFX WebView; rastreo de pedidos)");
        stage.setScene(new Scene(web, 820, 560));
        stage.show();
        web.getEngine().getLoadWorker().stateProperty().addListener((o, old, state) -> {
            if (state == Worker.State.SUCCEEDED) {
                web.getEngine().executeScript("LibMap.apply(" + json + ")");
            }
        });
        web.getEngine().loadContent(html);
        new Thread(() -> {
            try {
                Thread.sleep(seconds * 1000L);
                Platform.runLater(() -> {
                    try {
                        Object info = web.getEngine().executeScript(
                                "document.querySelectorAll('.leaflet-tile-loaded').length + ' teselas cargadas de ' + document.querySelectorAll('.leaflet-tile').length");
                        System.out.println("MAPA: " + info);
                        System.out.println("DEBUG: " + web.getEngine().executeScript(
                                "(function(){var m=LibMap.map;var t=document.querySelector('.leaflet-tile-pane');"
                                + "var tiles=[].slice.call(document.querySelectorAll('.leaflet-tile')).map(function(i){return i.src.split('/').slice(-3).join('/')+'@'+i.style.transform+'|'+i.style.width});"
                                + "return JSON.stringify({size:m.getSize(),zoom:m.getZoom(),center:m.getCenter(),win:[innerWidth,innerHeight],mapEl:[document.getElementById('map').clientWidth,document.getElementById('map').clientHeight],tilePane:t.style.transform,levels:[].slice.call(document.querySelectorAll('.leaflet-tile-container')).map(function(c){return c.style.zIndex+':'+c.style.transform+'|'+c.children.length}),tiles:tiles.slice(0,6)})})()"));
                        WritableImage img = web.snapshot(null, null);
                        PixelReader r = img.getPixelReader();
                        BufferedImage bi = new BufferedImage((int) img.getWidth(), (int) img.getHeight(), BufferedImage.TYPE_INT_ARGB);
                        for (int y = 0; y < bi.getHeight(); y++) {
                            for (int x = 0; x < bi.getWidth(); x++) {
                                bi.setRGB(x, y, r.getArgb(x, y));
                            }
                        }
                        ImageIO.write(bi, "png", out.toFile());
                    } catch (Exception e) {
                        e.printStackTrace();
                    }
                    Platform.exit();
                    System.exit(0);
                });
            } catch (InterruptedException ignored) {
                // saliendo
            }
        }).start();
    }

    public static void main(String[] args) {
        Application.launch(MapProbe.class, args);
    }
}
