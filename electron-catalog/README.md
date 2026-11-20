# Catálogo de libros para Windows 11

Aplicación Electron que consume exclusivamente el XML de un endpoint de libros. Habla con **una sola dirección: la del API Gateway** (Nginx → gateway → servicios). Cada servicio es una ruta de esa dirección: `/api/login` (login), `/api/books` (books, de donde sale el catálogo) y `/library` (portadas; el monolito vive en `/`). Por defecto usa el gateway de esta computadora, `http://localhost:8080`; en la instancia de GCP basta escribir su IP (cambia cada vez que se enciende), por ejemplo `34.51.109.238`. Se cambia en el panel **Dirección del gateway** de la pantalla de inicio de sesión y queda guardada en `localStorage`.

## Ejecutar

```powershell
cd electron-catalog
npm.cmd install
npm.cmd start
```

La app solicita el catálogo al abrirse y al pulsar **Actualizar**. La paginación es local después de cada petición XML. El endpoint debe devolver elementos `<book>` dentro de `<books>`.

Los campos `autor(es)`, `stock` y `año` se mostrarán como `No disponible` mientras el XML no los entregue; no se inventan ni se consultan fuentes adicionales.

## Imágenes en despliegue

La aplicación consulta `GET /books` y después `GET /books/images`. Este último debe existir en `services/soap/rest_api.py` y la base debe tener aplicada `services/soap/sql/ejercicio05_extension.sql`.

El XML de imágenes contiene rutas como `/uploads/portada.jpg`. Las portadas salen de la misma dirección del gateway, bajo `/library` (por ejemplo `http://<IP>/library/uploads/portada.jpg`); la app combina esa base con la ruta XML. La ruta debe ser pública y devolver `200` con `Content-Type: image/*` desde Windows.
