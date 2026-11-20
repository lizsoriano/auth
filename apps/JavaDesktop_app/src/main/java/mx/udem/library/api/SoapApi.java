package mx.udem.library.api;

import mx.udem.library.config.ServiceUrls;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * Integración demostrativa con el endpoint SOAP/XML del servicio Books ({@code POST /soap}, contrato en {@code GET /wsdl}):
 * se envía la operación {@code ObtenerConceptosPendientes} (document/literal, SOAP 1.1, sin filtros) y se muestra el XML.
 */
public final class SoapApi {

    public static final String REQUEST = """
            <?xml version="1.0" encoding="UTF-8"?>
            <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:lc="urn:library-classifier">
              <soapenv:Body>
                <lc:ObtenerConceptosPendientesRequest/>
              </soapenv:Body>
            </soapenv:Envelope>
            """;

    private final ServiceUrls urls;
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(6)).build();

    public SoapApi(ServiceUrls urls) {
        this.urls = urls;
    }

    public String send(String envelope) {
        HttpRequest request = HttpRequest.newBuilder(URI.create(urls.books() + "/soap")).timeout(Duration.ofSeconds(10))
                .header("Content-Type", "text/xml; charset=utf-8")
                .header("SOAPAction", "\"urn:library-classifier/ObtenerConceptosPendientes\"")
                .POST(HttpRequest.BodyPublishers.ofString(envelope, StandardCharsets.UTF_8)).build();
        try {
            HttpResponse<String> r = client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (r.statusCode() >= 400) {
                throw new ApiException(r.statusCode(), "soap_fault", "El servicio SOAP respondió HTTP " + r.statusCode() + ":\n" + r.body());
            }
            return r.body();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiException(0, "interrupted", "La operación fue interrumpida.");
        } catch (IOException e) {
            throw new ApiException(0, "network", "No se pudo conectar con el servicio SOAP.");
        }
    }
}
