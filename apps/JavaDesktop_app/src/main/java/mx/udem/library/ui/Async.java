package mx.udem.library.ui;

import javafx.concurrent.Task;

import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/** Ejecuta las llamadas de red fuera del hilo de JavaFX y entrega el resultado (o el error) en él. */
public final class Async {

    private static final ExecutorService POOL = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r, "library-io");
        t.setDaemon(true);
        return t;
    });

    private Async() {
    }

    public static <T> void run(AppContext ctx, Callable<T> work, Consumer<T> onSuccess) {
        run(work, onSuccess, ctx::handleError);
    }

    public static <T> void run(Callable<T> work, Consumer<T> onSuccess, Consumer<Throwable> onError) {
        Task<T> task = new Task<>() {
            @Override
            protected T call() throws Exception {
                return work.call();
            }
        };
        task.setOnSucceeded(e -> onSuccess.accept(task.getValue()));
        task.setOnFailed(e -> onError.accept(task.getException()));
        POOL.submit(task);
    }

    /** Para tareas en segundo plano sin interfaz (renovar el JWT): los errores se ignoran. */
    public static void quiet(Runnable work) {
        POOL.submit(work);
    }
}
