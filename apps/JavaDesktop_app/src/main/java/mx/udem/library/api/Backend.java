package mx.udem.library.api;

import mx.udem.library.config.ServiceUrls;

/** Reúne el cliente HTTP, la sesión y un objeto por microservicio. Es lo único que la interfaz necesita conocer. */
public final class Backend {

    private final HttpApi http;
    private final Session session;
    private final AuthApi auth;
    private final UsersApi users;
    private final BooksApi books;
    private final AuthorsApi authors;
    private final OrdersApi orders;
    private final PaymentsApi payments;
    private final TrackingApi tracking;
    private final SoapApi soap;

    public Backend(ServiceUrls urls) {
        this.session = new Session();
        this.http = new HttpApi(urls, session);
        this.auth = new AuthApi(http);
        this.users = new UsersApi(http);
        this.books = new BooksApi(http);
        this.authors = new AuthorsApi(http);
        this.orders = new OrdersApi(http);
        this.payments = new PaymentsApi(http);
        this.tracking = new TrackingApi(http);
        this.soap = new SoapApi(urls);
    }

    public HttpApi http() {
        return http;
    }

    public Session session() {
        return session;
    }

    public ServiceUrls urls() {
        return http.urls();
    }

    public AuthApi auth() {
        return auth;
    }

    public UsersApi users() {
        return users;
    }

    public BooksApi books() {
        return books;
    }

    public AuthorsApi authors() {
        return authors;
    }

    public OrdersApi orders() {
        return orders;
    }

    public PaymentsApi payments() {
        return payments;
    }

    public TrackingApi tracking() {
        return tracking;
    }

    public SoapApi soap() {
        return soap;
    }
}
