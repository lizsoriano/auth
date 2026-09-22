# Catálogo de libros para Windows 11

Aplicación Electron que consume exclusivamente el XML de un endpoint de libros. Por defecto usa `http://34.51.75.204:5001/books`; se puede cambiar desde **Configuración** y queda guardado en `localStorage`.

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

El XML de imágenes contiene rutas como `/uploads/portada.jpg`. Configura **Ubicación pública de imágenes** con el host que realmente las sirve, por ejemplo `http://<IP-O-DOMINIO>/library`; la app combina esa base con la ruta XML y persiste el valor en `localStorage`. La ruta debe ser pública y devolver `200` con `Content-Type: image/*` desde Windows.
