# Animación: cómo viaja una petición en Library (microservicios, JWT, Redis y PostgreSQL)

Animación interactiva publicada en mi cuenta de Ubiquitous:

**https://ubiquitous.udem.edu/~iac-637044/parcial2/Animacion2.html#books-miss/1**

Muestra al cliente (Python_app, Electron_app o web-monolito), el proxy Nginx, los 6 microservicios (Login, Books, Users, Authors, Pedidos y Pagos), cómo cada servicio consulta primero Redis y, cuando no lo encuentra (MISS), baja a PostgreSQL y deja una copia; con el JWT de 20 minutos, la revocación compartida, la idempotencia de pagos y qué pasa cuando Redis falla.

Cada caso tiene enlace directo, por ejemplo:

- Books, 1.ª consulta (MISS → PostgreSQL): https://ubiquitous.udem.edu/~iac-637044/parcial2/Animacion2.html#books-miss/1
- Books, escritura con JWT: https://ubiquitous.udem.edu/~iac-637044/parcial2/Animacion2.html#books-put/1
- Login y firma del JWT: https://ubiquitous.udem.edu/~iac-637044/parcial2/Animacion2.html#login/1

También está enlazada desde la página de Parcial 2 de mi portafolio (apartado 02 · Animación 2). La reflexión está en `reflexion.md`.
