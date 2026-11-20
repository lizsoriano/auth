# Cliente de escritorio (Tkinter) — los 6 microservicios de Library

Aplicación de escritorio en Python que consume, por HTTP, los **seis microservicios independientes** del proyecto
(cada uno en su propio puerto y con su propio rol de PostgreSQL):

| Microservicio | Puerto | Prefijo en la VM (Nginx) | Pestaña de la app |
|---|---|---|---|
| login | 5000 | `/auth` | Sesión y perfil (+ login / registro) |
| books | 5001 | `/soap` | Catálogo de libros · Libros (CRUD) |
| users | 5002 | `/users` | Usuarios |
| authors | 5003 | `/authors` | Autores |
| pedidos | 5004 | `/pedidos` | Pedidos |
| pagos | 5005 | `/pagos` | Pagos |

**No accede a PostgreSQL ni a Redis directamente**: todo pasa por los endpoints REST. Cada pestaña ofrece el CRUD
completo de su servicio con formularios y muestra el código HTTP que respondió el servidor.

## Versión de Python y biblioteca gráfica

- Python 3.12 (mínimo 3.10).
- **Tkinter** (incluido en la instalación estándar de Python en Windows).
- `requests` para el cliente HTTP (única dependencia de la app). Las pruebas con capturas usan además `pillow`.

## Estructura

```
apps/Python_app/
├── app.py            # GUI (Tkinter): login, panel principal, perfil, catálogo, libros, semáforos, configuración
├── service_tabs.py   # pestañas CRUD de Users, Authors, Pedidos y Pagos + bitácora de peticiones
├── api_client.py     # ÚNICO módulo que habla HTTP (requests) y maneja el JWT (renovación automática)
├── config.py         # Carga/guarda la dirección del gateway (y deriva las 6 rutas) en config.local.json
├── session_store.py  # Persistencia local de la cookie de sesión + email (nunca contraseña ni JWT)
├── tests/
│   ├── gui_integration.py   # prueba la GUI REAL contra los 6 servicios (incluye «Redis caído»)
│   └── capturas.py          # genera un PNG por pestaña (evidencia)
└── requirements.txt
```

Recorrido del código (de un botón a la respuesta): `app.py`/`service_tabs.py` (botón) → `api_client.py` (arma la
petición, pone `Authorization: Bearer`, renueva el JWT si hace falta) → microservicio → `api_client.py` interpreta
la respuesta (o lanza `ApiError` con un mensaje entendible) → la pestaña actualiza la pantalla.

## Instalación

```bash
cd apps/Python_app
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python app.py
```

## Configuración de la dirección

Pestaña **Configuración**: **una sola dirección, la del API Gateway** (Nginx → gateway → servicios). Cada microservicio es
una ruta de la API de esa dirección: `/api/login`, `/api/books`, `/api/users`, `/api/authors`, `/api/pedidos` y `/api/pagos`. La pestaña muestra las seis
URLs resultantes y tiene estos botones:

- **Esta computadora (localhost:8080):** el gateway de esta computadora (valor por omisión).
- **Probar conexión / Guardar / Restaurar valores predeterminados.**
- Para la VM basta escribir su IP (por ejemplo `34.51.109.238`; cambia cada vez que se enciende): se arman
  `http://<IP>/api/login`, `/api/books`… Los puertos 5000–5005 ya no se usan desde la app ni están abiertos al público.

`config.local.json` se crea junto al código (no se sube al repositorio) y solo guarda `gateway_url`. Una configuración
vieja con las seis URLs por Nginx se convierte sola a la dirección única.

## Seguridad: JWT, refresh y roles

- `POST /login` devuelve un **JWT HS256 de 20 minutos** (claims `user_id`, `role_id`, `jti`…) y un **refresh token de un
  solo uso**. La app los guarda **solo en memoria** (nunca en disco): al reabrirla se vuelve a pedir la contraseña.
- Cada petición lleva `Authorization: Bearer <JWT>`. La app **renueva el JWT antes de que caduque** (con menos de 3 min de
  vida, en segundo plano, con `POST /token/refresh`) y, si un servicio responde 401, lo renueva una vez y reintenta.
  La barra superior muestra el reloj del JWT («JWT expira en 19:53») y el botón **Renovar JWT ahora**.
- Los errores de seguridad se muestran con su código: **401** (sin token / token inválido, revocado o vencido; si no se
  puede renovar se vuelve al login), **403** (el rol no alcanza), **409** (regla de negocio), **503** (Redis o PostgreSQL
  no responden: el servicio falla cerrado y no modifica nada).
- Cerrar sesión borra la sesión y el refresh token **y revoca el JWT** (`jwt:revoked:<jti>` en Redis): el mismo token
  deja de servir en los 6 servicios.

| Rol (`role_id`) | Qué puede hacer en la app |
|---|---|
| admin (1) | Todo: usuarios, autores, libros, ve y gestiona todos los pedidos y pagos. |
| staff (2) | Autores y libros (escritura), ve y gestiona todos los pedidos, marca «enviado». Solo su propia cuenta en Users. |
| customer (3) | Lee catálogo y autores; crea, ve y cancela **solo sus** pedidos; paga solo los suyos; solo su cuenta. |

## Qué hace cada pestaña

- **Catálogo / Libros:** `GET /books` (con filtros del lado del cliente), detalle con conceptos e imágenes, y CRUD con
  `POST`, `GET`, `PUT` (reemplazo completo), `PATCH` (solo lo que se llena) y `DELETE` (con confirmación).
- **Autores:** `GET /authors` (público, con caché de Redis), `POST/PUT/PATCH/DELETE`, `GET /authors/{id}/books`,
  vincular y desvincular libros. Borrar un autor con libros vinculados da 409.
- **Usuarios:** `GET /users` (admin), `GET /users/me`, `GET/POST/PUT/PATCH/DELETE /users/{id}`, `PUT /users/{id}/password`
  y cambio de rol/estado (solo admin). El admin no puede borrarse a sí mismo (409).
- **Pedidos:** crear con varias líneas (ISBN × cantidad; descuenta stock), listar por estado, ver detalle, cancelar
  (`DELETE` o `PATCH status`; repone stock), «enviado» (staff/admin) y el botón **Pagar este pedido →** que abre Pagos con
  el pedido y su total. Marcar «pagado» a mano da 409: solo Pagos puede.
- **Pagos:** `POST /pagos` con la cabecera `Idempotency-Key` (se genera sola). **Reintentar con la MISMA clave** devuelve
  el pago original sin cobrar otra vez (`Idempotent-Replay: true`). Los pagos son inmutables: **Probar PUT/DELETE → 405**.
  Sin Redis no se cobra (503).
- **Sesión y perfil:** `GET /session`, `POST /session/extend`, `PATCH /profile`.
- **Semáforos:** verde / amarillo / rojo para cada microservicio y para Redis (se consulta `/health` cada 15 s).
  Verde = el servicio, PostgreSQL y Redis responden; amarillo = el servicio responde pero Redis (o PostgreSQL) no;
  rojo = no responde. Con Redis caído, los 6 pasan a amarillo y el de Redis a rojo.
- **Bitácora HTTP:** cada petición (método, servicio, ruta, código, milisegundos) con colores por código; exportable a CSV.
  Nunca guarda cuerpos, contraseñas ni tokens.

## Pruebas

`tests/gui_integration.py` maneja la GUI de verdad (llena campos y pulsa botones) contra los 6 servicios reales:
login por rol, 403 de customer, pedido → pago → reintento idempotente → 405, stock al pedir y cancelar, renovación del
JWT (manual y automática), JWT revocado tras cerrar sesión, CRUD completo de Users y Authors como admin y la fase
**Redis caído** (semáforos, 503 en users/pedidos/pagos y login, lecturas públicas siguen). No usa mocks y no toca
`config.local.json` ni la sesión guardada.

```bash
# 1) servicios arriba: local con Docker (bash e2e/serve_local.sh en el repo auth) o la VM
set LIB_BASE_PORT=15000                 # o: set LIB_VM=http://<IP-de-la-VM>
set LIB_DEMO_PASSWORD=...               # contraseña de demo-admin@ / demo-staff@ / demo-customer@example.com
set LIB_REDIS_CONTAINER=lib_redis_local # opcional: fase «Redis caído» (detiene y arranca ese contenedor)
python tests/gui_integration.py
python tests/capturas.py capturas admin # PNG de cada pestaña (requiere: pip install pillow)
```

## Problemas conocidos / limitaciones

- Las imágenes de portada se muestran como enlace (se abren en el navegador), no incrustadas.
- La búsqueda del catálogo es sobre lo ya cargado (cliente); no hay endpoint de búsqueda en el servidor.
- Un cambio de rol hecho por un admin se aplica al usuario hasta su siguiente renovación/login (≤ 20 min), porque el rol
  viaja dentro del JWT.
- Para HTTPS con el certificado autofirmado de la VM habría que usar `https://` en las URLs y confiar en el certificado.

## Solución de problemas frecuentes

| Síntoma | Causa |
|---|---|
| «No se pudo conectar con el servidor» | La dirección del gateway en Configuración no es correcta, o el gateway/servicio está apagado. Revisa Semáforos. |
| Todos los semáforos en rojo | La VM está apagada o su IP cambió: Configuración → escribe la IP nueva en «Dirección del gateway» → Guardar. |
| Todos en amarillo y Redis en rojo | Redis no responde: login, usuarios, pedidos y pagos dan 503 (falla cerrado); el catálogo público sigue. |
| 401 al operar | El JWT se revocó (otro cierre de sesión) o la sesión de 24 h terminó: vuelve a iniciar sesión. |
| 403 | Tu rol no tiene permiso para esa operación (es el comportamiento esperado de customer en Users/Authors). |
| `pip install` falla con «externally managed environment» | Crea el entorno virtual (`python -m venv .venv`) como indican los pasos de instalación. |
