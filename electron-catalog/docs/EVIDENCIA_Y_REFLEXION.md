# Evidencia y reflexión

## Capturas requeridas

Guarda estas capturas reales en `docs/capturas/` antes de subir la actividad:

1. `01_catalogo_xml.png`: tarjetas cargadas desde `/books`, con imagen, título, ISBN y precio.
2. `02_paginacion.png`: segunda página del catálogo.
3. `03_configuracion.png`: endpoint XML y ubicación pública de imágenes configurados.
4. `04_imagenes.png`: al menos una portada visible desde `/books/images`.

No se agregaron capturas simuladas: el servidor remoto no acepta conexiones desde este entorno, por lo que no sería evidencia honesta de resultados. Para generarlas, inicia `services/soap/app.py` con PostgreSQL, ejecuta `npm.cmd start` desde `electron-catalog` y captura la ventana con Recortes de Windows.

## Reflexión

La interfaz consume XML del microservicio y obtiene las portadas mediante el endpoint especializado `/books/images`. Separar ambas respuestas mantiene el catálogo básico ligero y permite cargar imágenes solo cuando se necesitan. Las rutas de imágenes se resuelven contra una base configurable y persistente porque, en un despliegue real, Flask puede vivir en un puerto distinto al servidor público que entrega archivos estáticos. Electron realiza la solicitud de red desde su proceso principal y entrega al renderizador solo el XML; esto preserva el aislamiento de la interfaz y evita depender de CORS.
