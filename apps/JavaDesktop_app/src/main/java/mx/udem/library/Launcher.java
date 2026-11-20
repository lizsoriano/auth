package mx.udem.library;

import javafx.application.Application;

/** Punto de entrada. Existe aparte de {@link LibraryApp} para poder ejecutar el .jar sin el módulo de JavaFX en el classpath. */
public final class Launcher {

    private Launcher() {
    }

    public static void main(String[] args) {
        Application.launch(LibraryApp.class, args);
    }
}
