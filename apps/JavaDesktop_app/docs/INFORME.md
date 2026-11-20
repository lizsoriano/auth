# Library Desktop - Documento de entrega

## Autora

| Nombre | Matrícula |
|---|---|
| Ruth Elizabeth Soriano Barrera | 637044 |

## A. Explicación de la aplicación

### Objetivo

Library Desktop es una aplicación de escritorio desarrollada en Java con JavaFX. Permite iniciar sesión, consultar libros, agregarlos a una cesta, simular una compra, revisar pedidos y seguir una entrega en un mapa de Monterrey.

En esta aplicación integré los microservicios del proyecto Library. Para hacerlo utilicé REST, WebSockets y una operación de demostración con SOAP. Su objetivo es mostrar cómo diferentes tecnologías pueden trabajar juntas dentro de un sistema distribuido.

### Organización de la aplicación

Desarrollé la interfaz con JavaFX. Desde ella, el usuario puede consultar el catálogo, realizar compras y revisar sus entregas.

Utilicé `HttpClient` de Java para enviar solicitudes a los microservicios. La información se intercambia principalmente en formato JSON y se procesa con Jackson.

Los servicios están publicados en una máquina virtual de Google Cloud Platform mediante Nginx. PostgreSQL guarda la información permanente y Redis se utiliza como apoyo en los servicios. La aplicación de escritorio no se conecta directamente con estas bases de datos.

Para el seguimiento de las entregas utilicé un servidor desarrollado con Flask y Flask-Sock. El mapa se muestra dentro de la aplicación mediante un WebView con Leaflet y OpenStreetMap.

### Microservicios utilizados

Integré los siguientes servicios:

* Login: inicio de sesión, renovación de tokens y cierre de sesión.
* Users: consulta y administración de usuarios según los permisos.
* Books: consulta de libros, portadas, detalles y una operación SOAP.
* Authors: consulta de autores y sus libros.
* Pedidos: creación, consulta y cancelación de pedidos.
* Pagos: registro y consulta de pagos.
* Rastreo: consulta del seguimiento y envío de actualizaciones por WebSocket.

Cada servicio tiene una responsabilidad específica. La aplicación reúne sus resultados para que el usuario pueda completar el proceso desde una misma interfaz.

### Inicio de sesión con JWT

El usuario escribe su correo y contraseña. La aplicación envía estos datos al servicio de Login, que los valida y devuelve un JWT y un token de renovación.

El JWT dura 20 minutos y se guarda en memoria. En las solicitudes protegidas se envía dentro del encabezado `Authorization`.

Antes de que expire, la aplicación solicita un nuevo token. El token de renovación es de un solo uso y se reemplaza por uno nuevo al utilizarlo.

Si un servicio responde que la sesión ya no es válida, la aplicación intenta renovarla y repetir la solicitud una vez. Si no lo consigue, borra la sesión y regresa al inicio de sesión.

Al cerrar sesión, se solicita la revocación del JWT y se eliminan los datos de sesión de la memoria. Las opciones administrativas se muestran según el rol del usuario, pero los servicios también comprueban sus permisos.

### Cesta y simulación de compra

La cesta se guarda en memoria mientras se utiliza la aplicación. Antes de comprar, se consultan nuevamente los libros para comprobar que el precio y las existencias sigan siendo los mismos. Si hubo cambios, la cesta se actualiza y se informa al usuario.

La compra sigue estos pasos:

1. Se crea el pedido y se descuenta el inventario.
2. Se registra el pago con el monto correspondiente.
3. Se consulta el estado actualizado del pedido.
4. Se solicita el seguimiento de la entrega.

El pago incluye una clave de idempotencia para evitar que un reintento registre dos veces la misma operación.

La aplicación no procesa datos bancarios reales. Solo registra el método de pago y el monto como parte de la simulación. Si el pago falla, el pedido queda pendiente y puede pagarse después o cancelarse desde Mis compras.

### Código de rastreo

Cada pedido recibe un código con un formato como este:

`LIB-MTY-2026-000125`

El código se genera a partir del año y del identificador del pedido. Esto permite volver a consultar el mismo seguimiento.

El usuario puede encontrarlo al confirmar la compra y en Mis compras. También puede escribirlo o seleccionarlo en la pantalla de rastreo.

### Seguimiento con WebSockets

Para seguir la entrega, la aplicación abre una conexión WebSocket y envía un mensaje con el JWT y el código de rastreo. El token se manda dentro del mensaje, evitando incluirlo en la dirección de conexión.

El servidor valida la sesión y consulta el servicio de Pedidos para comprobar que el pedido pertenece al usuario. También verifica que esté pagado. Si no cumple estas condiciones, rechaza el acceso.

Después envía la ruta inicial y una actualización de posición cada segundo. La entrega simulada comienza en la Macroplaza y sigue una ruta por calles de Monterrey.

La aplicación recibe las posiciones y actualiza el mapa. También muestra el estado del pedido, la calle, la velocidad y el avance. El pedido aparece como entregado cuando el vehículo llega al final de la ruta.

### Uso de SOAP

La aplicación incluye una demostración de SOAP mediante la operación `ObtenerConceptosPendientes` del servicio Books.

Para utilizarla, construye un mensaje XML con la estructura de SOAP 1.1 y lo envía al servicio. Esto permite mostrar otra forma de integración además de REST y WebSockets.

### Evidencias del funcionamiento

Incluí capturas de las pantallas y registros de pruebas realizadas contra los servicios reales.

Documenté 21 pruebas del cliente Java y 111 pruebas del servidor de rastreo. También comprobé que un usuario no pudiera consultar el seguimiento de un pedido ajeno, tanto por REST como por WebSocket.

## B. Reflexión sobre las tecnologías de integración

### REST

REST me permitió conectar la aplicación Java con los servicios de libros, usuarios, pedidos y pagos. Fue útil porque cada servicio se encarga de sus operaciones y la aplicación solo solicita la información que necesita. Así evité conectarme directamente a la base de datos y mantuve las validaciones y los permisos dentro de los servicios.

### WebSockets

WebSockets me permitió actualizar la posición del vehículo sin recargar el mapa. A diferencia de REST, donde tendría que preguntar por la ubicación cada cierto tiempo, el servidor envía las nuevas posiciones por una conexión que permanece abierta. También aprendí que debo considerar qué hacer si esa conexión se pierde.

### SOAP

La diferencia que identifiqué es que REST suele intercambiar información en JSON, mientras que SOAP utiliza mensajes XML con una estructura más estricta. SOAP puede ser útil al trabajar con empresas o sistemas que ya lo requieren. Para conectarlo con Java puedo enviar mensajes XML o utilizar herramientas que generen el cliente a partir de su contrato WSDL.

### Google Cloud Platform

Tener los servicios en GCP permite acceder a ellos desde distintas computadoras sin depender de que mi computadora esté encendida. Sin embargo, necesito Internet y que el servidor esté disponible. También debo proteger las conexiones, considerar que algunas solicitudes pueden tardar y aumentar los recursos si crece la cantidad de usuarios.

### PostgreSQL

PostgreSQL guarda los datos de usuarios, libros, pedidos y pagos. Es mejor que los servicios accedan a ella porque así se respetan las reglas del sistema y no se exponen sus credenciales en la aplicación Java. Esto también facilita cambiar la base de datos sin tener que modificar directamente todas las aplicaciones que la utilizan.

### Formas de comunicación

Aprendí que cada tecnología sirve para necesidades diferentes. Utilizaría REST para iniciar sesión, consultar libros y gestionar pedidos y pagos. Para el rastreo usaría WebSockets, porque necesito recibir ubicaciones continuamente. SOAP sería una opción cuando otro sistema lo solicite. En los pagos también debo cuidar que repetir una solicitud no registre dos veces la misma operación.

## C. Reflexión sobre el uso de inteligencia artificial

### ¿Qué herramienta de IA utilicé?

Utilicé Claude, de Anthropic, mediante Claude Code.

### ¿En qué actividades me apoyé?

Me apoyé en Claude para revisar las rutas, los datos JSON y los errores de los servicios. También lo utilicé para organizar la aplicación, desarrollar los clientes REST y WebSocket, trabajar en la interfaz JavaFX, preparar pruebas y hacer los ajustes necesarios en el servidor de rastreo. Además, me ayudó a generar las capturas de evidencia.

### ¿Qué instrucciones fueron más útiles?

Me sirvió pedirle que partiera del código existente y que no inventara rutas ni formatos de datos. También le indiqué que utilizara JWT en las operaciones protegidas, que no conectara Java directamente a la base de datos y que trabajara con los servicios reales. Pedirle que probara las funciones, en lugar de dar por hecho que funcionaban, me ayudó a encontrar errores.

### ¿Qué errores o limitaciones presentó el código generado?

Encontré varios detalles al ejecutar la aplicación:

* La consulta `GET /pedidos` no incluía los productos de cada pedido. Al ver la tabla vacía, revisé la respuesta y ajusté la consulta para utilizar `GET /pedidos/{id}`.
* La cesta intentaba actualizar la interfaz desde un hilo de red. Corregí el aviso para que se ejecutara en el hilo de JavaFX.
* El emoji del camión no se veía bien en el WebView. Lo cambié por un ícono SVG.
* El mapa no se ajustaba correctamente al tamaño de la ventana. Agregué `invalidateSize` cuando cambiaba su tamaño.
* Books no tenía un campo de descripción. Utilicé los datos reales disponibles para mostrar información del libro y dejé documentada esa limitación.
* Una captura incluía otra ventana del escritorio. La descarté y cambié la captura para mostrar solamente la aplicación.

### ¿Qué modificaciones realicé para que funcionara correctamente?

Además de esas correcciones, agregué al servidor de rastreo la validación del JWT y la consulta al servicio Pedidos para comprobar a quién pertenecía cada pedido. Probé que otro usuario no pudiera rastrear un pedido ajeno, ajusté el parámetro `limit` al valor que acepta el servicio y revisé que no quedaran contraseñas ni tokens guardados en archivos.

### ¿Qué conceptos de integración comprendí mejor?

Comprendí que primero debo revisar las rutas, los formatos y los errores de cada servicio. También entendí que iniciar sesión no significa tener acceso a todos los pedidos: el servicio debe comprobar a quién pertenece cada uno. En esta aplicación envié el JWT dentro de un mensaje del WebSocket, en lugar de ponerlo en la URL. Además, me quedó más clara la diferencia entre consultar una ubicación repetidamente y recibir las actualizaciones que envía el servidor.

### ¿Qué partes del proyecto podría desarrollar sin asistencia de IA?

Con lo que practiqué, podría hacer pantallas sencillas, validar entradas, manejar la cesta en memoria y realizar consultas REST básicas siguiendo la documentación. Todavía necesito practicar más la renovación de sesiones, WebSockets y la integración del mapa. La IA me ayudó a avanzar, pero tuve que revisar y probar sus propuestas para comprobar que funcionaran y poder explicar el código.

## D. Monorepo y video demostrativo

**Monorepo compactado:** `Library_Monorepo_Soriano.zip` (el monorepo Library completo, incluida la aplicación en `apps/JavaDesktop_app`, el servidor de rastreo en `services/gps` y los archivos de despliegue en `deploy/`; sin `.git`, entornos virtuales, `node_modules` ni archivos `.env`).

**Video demostrativo en YouTube:** https://youtu.be/PcUTY99GrAY
