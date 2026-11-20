package mx.udem.library.ui;

import javafx.application.Platform;
import javafx.stage.Stage;
import mx.udem.library.api.ApiException;
import mx.udem.library.api.Backend;
import mx.udem.library.api.SessionExpiredException;
import mx.udem.library.cart.Cart;
import mx.udem.library.cart.PurchaseService;
import mx.udem.library.config.ConfigStore;
import mx.udem.library.config.ServiceUrls;

/** Estado compartido por todas las vistas: conexión con los servicios, cesta y navegación. */
public final class AppContext {

    /** Secciones de la ventana principal. */
    public enum Section { CATALOG, CART, ORDERS, TRACKING, PROFILE, ADMIN, SOAP }

    /** Lo que las vistas pueden pedirle a la ventana principal. */
    public interface Navigator {
        void go(Section section);

        /** Abre «Rastreo» con ese código y empieza a seguir el pedido. */
        void track(String code);
    }

    public final Stage stage;
    public final ConfigStore store;
    public final Cart cart = new Cart();
    private Backend backend;
    private PurchaseService purchases;
    private Navigator navigator;
    private Runnable showLogin = () -> { };

    public AppContext(Stage stage, ConfigStore store) {
        this.stage = stage;
        this.store = store;
        connect(store.load());
    }

    /** (Re)crea el cliente con otras direcciones de servicios; la sesión anterior se descarta. */
    public void connect(ServiceUrls urls) {
        this.backend = new Backend(urls);
        this.purchases = new PurchaseService(backend.books(), backend.orders(), backend.payments(), backend.tracking());
        this.cart.clear();
    }

    public Backend backend() {
        return backend;
    }

    public PurchaseService purchases() {
        return purchases;
    }

    public Navigator nav() {
        return navigator;
    }

    public void nav(Navigator navigator) {
        this.navigator = navigator;
    }

    public void onShowLogin(Runnable showLogin) {
        this.showLogin = showLogin;
    }

    public void logoutLocal() {
        backend.session().clear();
        cart.clear();
        showLogin.run();
    }

    /** Manejo común de errores de cualquier llamada: sesión vencida vuelve al login; lo demás se muestra. */
    public void handleError(Throwable error) {
        Runnable r = () -> {
            if (error instanceof SessionExpiredException) {
                Dialogs.info(stage, "Sesión expirada", error.getMessage());
                logoutLocal();
            } else if (error instanceof ApiException api) {
                Dialogs.error(stage, api.isNetwork() ? "Sin conexión" : "No se pudo completar la operación", api.getMessage());
            } else {
                Dialogs.error(stage, "Error inesperado", String.valueOf(error.getMessage()));
            }
        };
        if (Platform.isFxApplicationThread()) {
            r.run();
        } else {
            Platform.runLater(r);
        }
    }
}
