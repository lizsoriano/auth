# gps — Rastreo GPS en tiempo real (Flask + Flask-Sock + Leaflet)

Utilicé este microservicio para recibir posiciones de vehículos por WebSocket y mostrarlas en vivo a los mapas web conectados. Incluye el mapa: **HTML + CSS + JavaScript con Leaflet y OpenStreetMap**, con un diseño inspirado en Google Maps. Escucha en `0.0.0.0:5900`.

```
GPSapp (Python, escritorio) ──ws role=gps──▶  Flask + Flask-Sock  ──ws role=map──▶  Mapa web
 vehículos por las CALLES REALES               valida · guarda estado             Leaflet + OSM
 de Monterrey (GeoJSON de OSRM)                e historial · difunde en GeoJSON   index.html + styles.css + map.js
 (carpeta ../../gpsapp)                        · identifica calles (Nominatim)
```

## Ejecutar

```bash
cd services/gps
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt     # Linux/macOS: .venv/bin/python
.venv/Scripts/python app.py
```

- Mapa: <http://localhost:5900/> (necesita internet para Leaflet y los mosaicos de OpenStreetMap).
- Health check: <http://localhost:5900/health>.
- Simulador: ver [`../../gpsapp/README.md`](../../gpsapp/README.md).

Variables opcionales: `GPS_HOST` (0.0.0.0), `GPS_PORT` (5900), `GPS_HISTORY_SIZE` (500 posiciones por vehículo), `GPS_LOG_LEVEL` (INFO).

## El mapa web (HTML, CSS y Leaflet)

| Archivo | Qué hace |
|---|---|
| `gps_service/static/index.html` | Estructura de la página; carga **Leaflet 1.9.4** (con huella SRI) y los otros dos archivos. |
| `gps_service/static/styles.css` | Todo el diseño: panel flotante con buscador, tarjetas, indicadores, marcadores con pulso y ventanas de información tipo Google Maps. Se adapta a pantallas pequeñas (el panel pasa abajo). |
| `gps_service/static/map.js` | Lógica con Leaflet: mosaicos OpenStreetMap, rutas `L.geoJSON` con borde blanco, vehículos con su flecha de rumbo y estela, WebSocket con reconexión, buscador por vehículo o calle. |

Qué se puede hacer: **tocar un vehículo** (tarjeta con calle, km/h ahora, km/h promedio y km recorridos, más «Ver recorrido» y «¿Qué calle es?»), **tocar cualquier punto del mapa** (identifica su calle), activar o apagar las capas *Rutas*, *Estelas*, *Semáforos* (cambian de color con la hora simulada: verde, amarillo, rojo; intermitentes de noche), *Cruces*, *Topes y baches* y *Escuelas*; el panel *Horario simulado* muestra la hora, el día y si hay hora pico, horario escolar o noche. Cada vehículo muestra qué hace («Esperando semáforo en rojo», «Cediendo el paso a peatones»…), **buscar** un vehículo o una calle, y «Ver todo». Arriba a la derecha: el número de vehículos y la **velocidad promedio de la flota** (Σ distancia ÷ Σ tiempo).

## Protocolo WebSocket

Endpoint: `ws://localhost:5900/ws?role=gps|map`. Cualquier otro `role` recibe un mensaje `error` y se cierra con el código 1008.

**role=gps** — el simulador envía un objeto, o una lista de **hasta 100** objetos (un lote por ciclo escala mucho mejor que un mensaje por vehículo):

```json
{"vehicle_id": "V001", "latitude": 25.6866, "longitude": -100.3161, "speed": 45.5, "heading": 270,
 "street": "Avenida Constitución", "avg_speed": 38.5, "trip_distance_m": 5120.4, "trip_time_s": 480}
```

| Campo | Regla |
|---|---|
| `vehicle_id` | obligatorio; 1 a 32 caracteres: letras, números, `_` o `-` |
| `latitude` / `longitude` | obligatorios; numéricos, −90…90 y −180…180 |
| `speed` | opcional (0 por defecto); km/h, 0…400 |
| `heading` | opcional (0 por defecto); grados, 0…360 (360 se guarda como 0) |
| `event` | opcional; qué le pasa al vehículo: `traffic_signals`, `crossing`, `stop`, `bump`, `pothole`, `school`, `rush`, `night` o `clear` |
| `event_text` | opcional; el evento en texto (hasta 120 caracteres), p. ej. «Esperando semáforo en rojo» |
| `sim_time`, `sim_day` | opcionales; hora simulada `HH:MM` o `HH:MM:SS` y día (0 = lunes … 6 = domingo) |
| `street` | opcional; calle actual (texto de hasta 120 caracteres; se limpian los caracteres de control) |
| `avg_speed` | opcional; km/h promedio del viaje, 0…400 |
| `trip_distance_m`, `trip_time_s` | opcionales; metros recorridos y segundos transcurridos desde que arrancó el viaje (0…1e9) |

Si algo no cumple, el servicio responde `{"type": "error", "message": "..."}` y no difunde nada (en una lista, un elemento inválido rechaza el mensaje completo). El canal sigue abierto. El servidor añade `timestamp` (UTC) a cada posición.

**role=map** — el servicio envía:

- `{"type": "snapshot", "vehicles": [...]}` al conectar: estado actual de cada vehículo más `trail` (sus últimas 50 posiciones como `[lat, lon]`).
- `{"type": "update", "vehicle": {...}, "feature": {...}}` cuando llega **una** posición; `feature` es la misma posición como GeoJSON `Point`.
- `{"type": "updates", "vehicles": [...], "features": {FeatureCollection}}` cuando llega un **lote**: un solo mensaje por lote, no uno por vehículo.
- `{"type": "pong"}` si el mapa envía `{"type": "ping"}`.

## HTTP

| Ruta | Respuesta |
|---|---|
| `GET /` | el mapa web |
| `GET /static/styles.css`, `/static/map.js` | CSS y JavaScript del mapa |
| `GET /health` | `{"status": "ok", "service": "gps", "vehicles": n, "clients": {"gps": n, "map": n}}` |
| `GET /vehicles` | estado actual de todos los vehículos |
| `GET /vehicles/<id>/history` | historial del vehículo (404 si no existe) |
| `GET /geojson/vehicles` | **GeoJSON** `FeatureCollection` de `Point` con la posición actual de cada vehículo (`application/geo+json`) |
| `GET /geojson/routes` | **GeoJSON** de las 4 rutas reales por las calles (LineString con las calles de cada tramo) |
| `GET /geojson/signals` | **GeoJSON** de semáforos, cruces peatonales, altos, topes, zonas escolares (OpenStreetMap) y baches (simulados) sobre las rutas, con los **horarios** (`schedule`) |
| `GET /vehicles/<id>/track.geojson` | recorrido del vehículo como `LineString` con distancia y **velocidad promedio** (404 si no existe) |
| `GET /geocode/reverse?lat=&lon=` | calle, colonia y ciudad de un punto con **Nominatim / OpenStreetMap** (400 parámetros inválidos, 422 fuera de Monterrey, 502 si Nominatim no responde) |

GeoJSON guarda las coordenadas como **[longitud, latitud]** (al revés que `latitude`/`longitude` del contrato JSON).

## Servicios gratuitos de OpenStreetMap

| Servicio | Para qué se usa | Reglas de uso |
|---|---|---|
| Mosaicos de OpenStreetMap | el fondo del mapa (Leaflet) | uso ligero y con atribución («© OpenStreetMap contributors», incluida en el mapa) |
| **OSRM** (`router.project-osrm.org`) | calcular las rutas reales por las calles, en GeoJSON | servidor de demostración: se piden **una vez** (en `gpsapp`) y se guardan en `data/rutas_monterrey.geojson` |
| **Overpass API** (`overpass-api.de`) | semáforos, cruces, altos, topes y escuelas reales de OpenStreetMap | se piden **una vez** (`gpsapp/hazards.py --refresh`, con reintentos) y se guardan en `data/senales_viales.geojson`; los baches son simulados |
| **Nominatim** (`nominatim.openstreetmap.org`) | saber qué calle es un punto (geocodificación inversa) | **máximo 1 petición por segundo**, con `User-Agent` que identifique la app; aquí: límite de 1 req/s, caché de ~10 m, solo al tocar el mapa y solo dentro de Monterrey |

`gps_service/geocode.py` implementa esas reglas. No se consulta a Nominatim por cada posición de cada vehículo: las calles de los vehículos ya vienen en el GeoJSON de las rutas.

## Decisiones y límites

- **Estado en memoria**: al reiniciar el servicio se pierde el historial; el simulador lo repuebla en segundos. Por eso debe correr **un solo proceso** (con gunicorn: `-w 1 --threads 50`, no lo probé aquí porque trabajé en Windows). No usa PostgreSQL ni Redis.
- **Escala**: un lote de hasta 100 posiciones es un solo mensaje y un solo `broadcast`; la lista lateral del mapa se redibuja como máximo 2 veces por segundo. Probado: 100 vehículos × 5 lotes en menos de 3 s.
- **Autenticación del canal original**: el endpoint `/ws?role=gps|map` no exige una sesión. Lo mantuve separado del rastreo de pedidos en `/ws/tracking`, donde agregué validación de JWT y permisos sobre el pedido. El canal original necesita protección adicional antes de publicarse en Internet.
- Para el rastreo de pedidos preparé `deploy/nginx-gps-proxy.conf` y `deploy/setup_gps_vm.sh`, con las cabeceras necesarias para WebSocket. La ejecución de ese despliegue en GCP sigue pendiente.
- El mapa se reconecta solo con espera creciente (1 → 10 s) y marca un vehículo como "sin señal" tras 15 s sin posiciones.
- `gps_service/data/rutas_monterrey.geojson` es la **misma** ruta que usa el simulador (`gpsapp/data/`); hay una prueba que las compara. Para regenerarlas: `python gpsapp/routing.py --refresh` (escribe las dos).

## Pruebas

```bash
.venv/Scripts/python -m pytest        # 68 pruebas: validación, HTTP, GeoJSON, Nominatim (simulado), WebSocket contra un servidor real y 100 vehículos
```
