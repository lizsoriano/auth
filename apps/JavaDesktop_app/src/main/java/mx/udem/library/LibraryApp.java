package mx.udem.library;

import javafx.application.Application;
import javafx.scene.Scene;
import javafx.stage.Stage;
import mx.udem.library.config.ConfigStore;
import mx.udem.library.model.User;
import mx.udem.library.ui.AppContext;
import mx.udem.library.ui.DemoRunner;
import mx.udem.library.ui.LoginView;
import mx.udem.library.ui.ShellView;
import mx.udem.library.ui.Ui;

/** Aplicación JavaFX de escritorio del proyecto Library. */
public final class LibraryApp extends Application {

    private AppContext ctx;
    private ShellView shell;

    @Override
    public void start(Stage stage) {
        ctx = new AppContext(stage, new ConfigStore());
        ctx.onShowLogin(this::showLogin);
        stage.setTitle("Library · cliente de escritorio");
        stage.setMinWidth(1000);
        stage.setMinHeight(640);
        Scene scene = new Scene(new javafx.scene.layout.Pane(), 1280, 780);
        scene.getStylesheets().add(Ui.stylesheet());
        stage.setScene(scene);
        showLogin();
        stage.show();
        stage.setOnCloseRequest(e -> {
            if (shell != null) {
                shell.tracking().stop();
            }
            javafx.application.Platform.exit();
            System.exit(0);
        });
        DemoRunner.maybeRun(ctx, this);
    }

    public LoginView showLogin() {
        shell = null;
        LoginView login = new LoginView(ctx, this::showShell);
        ctx.stage.getScene().setRoot(login);
        return login;
    }

    public ShellView showShell(User user) {
        shell = new ShellView(ctx);
        ctx.stage.getScene().setRoot(shell);
        return shell;
    }

    public ShellView shell() {
        return shell;
    }
}
