# Library Desktop (Java + JavaFX)

Desarrollé esta aplicación de escritorio como cliente del proyecto **Library**. Se autentica con **JWT**, consulta el catálogo (Books + Authors), arma una cesta, simula una compra (Pedidos + Pagos), muestra *Mis compras* y sigue la entrega de un pedido **en un mapa de Monterrey** con **WebSockets** (servidor Flask + Flask-Sock, mapa Leaflet + OpenStreetMap dentro de un `WebView`).

La aplicación utiliza **REST/JSON** para sus operaciones habituales, WebSocket para el rastreo y una operación SOAP/XML como demostración. No tiene driver de PostgreSQL ni accede a ninguna base de datos.

```
                    ┌─────────────────────────── App Java (JavaFX) ───────────────────────────┐
 Usuario ──────────►│ LoginView · Catálogo · Cesta · Mis compras · Rastreo (WebView+Leaflet)   │
                    │      │ HttpApi (HttpClient + JWT)            │ TrackingClient (WebSocket)│
                    └──────┼───────────────────────────────────────┼───────────────────────────┘
                REST + JSON│ Authorization: Bearer <JWT>           │ ws://…/ws/tracking (JWT en el 1.er mensaje)
   ┌─────┬──────┬──────┬──────┴─┬────────┬───────┐        ┌────────▼─────────┐  GET /pedidos/<id> con el mismo JWT
 login  books  users authors  pedidos   pagos    soap     │ gps (Flask-Sock) ├──────────────► pedidos (¿es de este usuario?)
 :5000  :5001  :5002 :5003    :5004     :5005    /soap    └──────────────────┘
        └──────────── PostgreSQL + Redis (solo los usan los servicios) ──────────┘
```

## Cómo ejecutar la aplicación

Requisitos: **JDK 21**, **Maven 3.9** y conexión a Internet (el mapa carga Leaflet y las teselas de OpenStreetMap).

```bash
cd apps/JavaDesktop_app
mvn javafx:run          # compila y abre la ventana
mvn test                # 21 pruebas unitarias
```

En la pantalla de inicio de sesión, el panel plegable **«Conexión con los servicios»** pide **una sola dirección: la del API Gateway**. Cada servicio es una ruta de esa dirección, así que cambiar de computadora o de instancia es cambiar un solo valor:

| Dirección del gateway | Dónde |
|---|---|
| `http://localhost:8080` (por omisión) | el gateway de esta computadora (`services/gateway`) |
| `34.51.109.238` (basta la IP) | la instancia de GCP, detrás de Nginx en el puerto 80 |

| Ruta (la API) | Servicio |
|---|---|
| `/api/login` | Login (JWT, renovación, cierre de sesión) |
| `/api/books` | Books (catálogo y SOAP) |
| `/api/users`, `/api/authors`, `/api/pedidos`, `/api/pagos` | Users, Authors, Pedidos, Pagos |
| `/api/gps` | Rastreo (REST y WebSocket `/api/gps/ws/tracking`) |
| `/library` | Portadas: lo sirve el monolito, que vive en `/` |

La dirección se guarda en `~/.library-desktop/config.json` (solo direcciones). **La contraseña y los tokens nunca se guardan**: el JWT vive en memoria.

### Levantar los servicios en local (para probar sin la instancia)

```bash
PG_PORT=55432 bash e2e/serve_local.sh                       # 6 microservicios + Redis; imprime la contraseña de las cuentas demo
# servidor de rastreo y gateway (mismo JWT_SECRET_KEY que login; en local sale del contenedor):
cd services/gps
JWT_SECRET_KEY=$(docker exec lib_serve_app printenv JWT_SECRET_KEY) PEDIDOS_URL=http://localhost:15004 python app.py
# gateway (:8080), apuntando a los puertos de serve_local.sh:
cd ../gateway
AUTH_URL=http://127.0.0.1:15000 SOAP_URL=http://127.0.0.1:15001 USERS_URL=http://127.0.0.1:15002 AUTHORS_URL=http://127.0.0.1:15003 \nPEDIDOS_URL=http://127.0.0.1:15004 PAGOS_URL=http://127.0.0.1:15005 GPS_URL=http://127.0.0.1:5900 python app.py
```

### Despliegue del rastreo en la instancia de GCP

`deploy/setup_gps_vm.sh` (se ejecuta en la VM con `sudo`) instala `services/gps` detrás de Nginx en `/gps/`, con el mismo `JWT_SECRET_KEY` de login y sin abrir puertos nuevos en el firewall. Archivos: `deploy/gps.service`, `deploy/nginx-gps-proxy.conf` (con las cabeceras de WebSocket). Dejé los pasos pendientes al final de este documento.

## Módulos del ejercicio y dónde está cada uno

| Módulo | Qué hace | Código |
|---|---|---|
| 1 · Autenticación y usuario | Login con correo y contraseña → JWT; muestra el usuario; perfil (`GET /users/me`); cerrar sesión (`POST /logout`); renueva el JWT solo (`POST /token/refresh`, un solo uso) y, si no puede, vuelve al login | `LoginView`, `ProfileView`, `api/HttpApi`, `api/Session`, `api/AuthApi` |
| 2 · Catálogo | Portada, título, autores, descripción, precio, ISBN, disponibilidad; búsqueda por título; detalle con biografía del autor | `CatalogView`, `BookDetailDialog`, `api/BooksApi`, `api/AuthorsApi` |
| 3 · Cesta | Agregar, cambiar cantidades (sin pasar del stock), quitar, subtotal/total; **valida precios y stock contra Books antes de comprar** | `cart/Cart`, `CartView`, `cart/PurchaseService.validate` |
| 4 · Compra simulada | Pedido (Pedidos) → pago simulado con `Idempotency-Key` (Pagos) → confirmación y código de rastreo | `CheckoutFlow`, `cart/PurchaseService`, `api/OrdersApi`, `api/PaymentsApi` |
| 5 · Mis compras | Pedidos del usuario con libros, total, estado de compra y de pago, código de rastreo; pagar o cancelar un pendiente | `OrdersView` |
| 6 · Rastreo | Código → WebSocket → mapa con vehículo, ruta, ubicación, avance y estados; «Volver a consultar» por REST | `TrackingView`, `tracking/TrackingClient`, `resources/tracking-map.html` |
| Extra | Administración (solo admin/staff) y una integración **SOAP/XML** demostrativa contra `POST /soap` | `AdminView`, `SoapView`, `api/SoapApi` |

## Endpoints que consume (tomados del código de los servicios)

| Servicio | Operaciones |
|---|---|
| Login | `POST /login`, `POST /token/refresh`, `POST /logout` |
| Users | `GET /users/me`, `GET /users` (admin) |
| Books | `GET /books`, `GET /books/images`, `GET /books/{isbn}`, `POST /soap` |
| Authors | `GET /authors`, `GET /authors/{id}/books` |
| Pedidos (JWT) | `POST /pedidos`, `GET /pedidos`, `GET /pedidos/{id}`, `DELETE /pedidos/{id}` |
| Pagos (JWT) | `POST /pagos` (cabecera `Idempotency-Key`), `GET /pagos?order_id=` |
| Rastreo (JWT) | `POST /tracking`, `GET /tracking/{código}`, `WS /ws/tracking` |

Todas las llamadas protegidas llevan `Authorization: Bearer <token>`. Un 401 renueva el token y reintenta **una** vez; si aún falla se limpia la sesión y se pide autenticarse de nuevo.

## Cambios que hice al servidor GPS para rastrear pedidos

El servicio GPS original solo difundía posiciones, sin pedidos ni usuarios. Hice una **adaptación mínima** en `services/gps/gps_service/tracking.py` (+ rutas en `app.py`):

- **Código** `LIB-MTY-<año>-<id del pedido a 6 dígitos>` (p. ej. `LIB-MTY-2026-000125`), derivado del pedido real: el mismo pedido siempre tiene el mismo código.
- **Autorización por sesión:** el servidor valida el JWT (HS256, `iss`, `exp`, claims) y confirma con el servicio **Pedidos** (`GET /pedidos/{id}` con el mismo Bearer) que el pedido es de ese usuario; staff/admin ven todos. Un pedido ajeno responde 404 y no revela que existe. El token va en el **primer mensaje** del WebSocket, no en la URL.
- **Solo pedidos pagados** (`pagado` o `enviado`): nunca se rastrea un pago inventado.
- **Una simulación por pedido:** ruta y destino dependen del pedido (4 rutas reales de OSRM por Monterrey y varios destinos). Estados: confirmado → preparando → enviado → en ruta → entregado; **«Entregado» solo ocurre al llegar al final de la ruta**.
- Límites documentados: el estado vive en memoria (si el servidor se reinicia, la simulación de ese pedido empieza de nuevo) y el tiempo del recorrido va 30× más rápido que el real.

Protocolo del WebSocket: cliente → `{"type":"auth","token":…,"code":…}`; servidor → `snapshot` (con la ruta completa) y luego un `update` por segundo; el cliente manda `ping` cada 20 s y `refresh` con el JWT nuevo cuando la sesión lo renueva; si el token vence, el servidor cierra con `token_expired`.

## Limitaciones que encontré en los servicios y cómo las resolví

| Necesidad | Qué pasa | Adaptación |
|---|---|---|
| Descripción del libro | Books no tiene campo «descripción» | Se arma con categoría, año y la **biografía del autor** (Authors). Si Books agrega ese campo, solo cambia `Book.description` |
| Autores de un libro | Authors no ofrece «autores de un libro» | Se consultan los libros de cada autor (en paralelo) y se invierte la relación |
| Portadas | Books devuelve rutas `/uploads/…`; las sirve el **monolito** (`/library`), no Books | `ServiceUrls.images` es configurable; sin imagen se muestra «Portada no disponible» |
| Código de rastreo | Ningún servicio lo genera | Lo genera el servidor de rastreo a partir del pedido real (arriba) |
| Detalle de pedido | `GET /pedidos` no trae las líneas | Al elegir un pedido se pide `GET /pedidos/{id}` |

## Pruebas y evidencias

- `mvn test`: **21 pruebas** del cliente (HTTP + JWT con servidor falso del JDK, renovación y expiración del token, cesta, validación de precios, flujo de compra, código de rastreo, configuración sin secretos). Servidor de rastreo: **111 pruebas** (`services/gps/tests`).
- `evidencias/capturas/`: capturas generadas por la propia app contra los servicios reales (login, catálogo, cesta, mis compras, rastreo en cuatro momentos, perfil, administración, SOAP) y `demo_log.txt` con lo que ocurrió. Las genera `DemoRunner` (`-Dlibrary.demo.dir=…`) con credenciales del entorno (`LIBRARY_DEMO_USER` y `LIBRARY_DEMO_PASSWORD`); la compra del recorrido se dispara por código con las mismas clases que usa la interfaz. Las portadas de esas capturas son imágenes de prueba generadas para la demostración local.
- `evidencias/autorizacion_rastreo.txt`: comprobación en vivo de que otro cliente no puede rastrear un pedido ajeno (404 por REST y por WebSocket), de que un token falso o la falta de token se rechazan y de que un pedido sin pagar no se rastrea (`verificar_autorizacion.py`).

## Pendiente

- Desplegar `deploy/setup_gps_vm.sh` en la instancia de GCP (no se ejecutó: requiere encenderla y publicar el código en `/opt/auth`).
- Las portadas reales dependen de que el monolito esté publicado en `/library` en la instancia.
