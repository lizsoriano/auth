# gps — Rastreo GPS en tiempo real (Flask + Flask-Sock)

Microservicio que recibe posiciones de vehículos por WebSocket y las difunde en vivo a los mapas web conectados. Incluye el mapa (HTML + JavaScript + Leaflet + OpenStreetMap). Escucha en `0.0.0.0:5900`.

```
GPSapp (Python, escritorio) ──ws role=gps──▶  Flask + Flask-Sock  ──ws role=map──▶  Mapa web
 simula vehículos en Monterrey                 valida · guarda estado             Leaflet + OSM
 (carpeta ../../gpsapp)                        actual e historial · difunde       (static/index.html)
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

## Protocolo

Endpoint WebSocket: `ws://localhost:5900/ws?role=gps|map`. Cualquier otro `role` recibe un mensaje `error` y se cierra con el código 1008.

**role=gps** — el simulador envía un objeto, o una lista de hasta 100 objetos:

```json
{"vehicle_id": "V001", "latitude": 25.6866, "longitude": -100.3161, "speed": 45.5, "heading": 270}
```

| Campo | Regla |
|---|---|
| `vehicle_id` | obligatorio; 1 a 32 caracteres: letras, números, `_` o `-` |
| `latitude` / `longitude` | obligatorios; numéricos, −90…90 y −180…180 |
| `speed` | opcional (0 por defecto); km/h, 0…400 |
| `heading` | opcional (0 por defecto); grados, 0…360 (360 se guarda como 0) |

Si algo no cumple, el servicio responde `{"type": "error", "message": "..."}` y no difunde nada (en una lista, un elemento inválido rechaza el mensaje completo). El canal sigue abierto. El servidor añade `timestamp` (UTC) a cada posición.

**role=map** — el servicio envía:

- `{"type": "snapshot", "vehicles": [...]}` al conectar: estado actual de cada vehículo más `trail` (sus últimas 50 posiciones como `[lat, lon]`).
- `{"type": "update", "vehicle": {...}}` cada vez que llega una posición válida.
- `{"type": "pong"}` si el mapa envía `{"type": "ping"}`.

## HTTP

| Ruta | Respuesta |
|---|---|
| `GET /` | el mapa web |
| `GET /health` | `{"status": "ok", "service": "gps", "vehicles": n, "clients": {"gps": n, "map": n}}` |
| `GET /vehicles` | estado actual de todos los vehículos |
| `GET /vehicles/<id>/history` | historial del vehículo (404 si no existe) |

## Decisiones y límites

- **Estado en memoria**: al reiniciar el servicio se pierde el historial; el simulador lo repuebla en segundos. Por eso debe correr **un solo proceso** (con gunicorn: `-w 1 --threads 50`, sin probar aquí porque este desarrollo fue en Windows). No usa PostgreSQL ni Redis.
- **Sin autenticación**: igual que el ejercicio de la arquitectura, cualquiera que alcance el puerto puede publicar o escuchar. No lo expongas a Internet sin un proxy que autentique y use `wss://`.
- Nginx necesitaría `proxy_http_version 1.1` y las cabeceras `Upgrade`/`Connection` para el WebSocket; no está configurado en `deploy/`.
- El mapa se reconecta solo con espera creciente (1 → 10 s) y marca un vehículo como "sin señal" tras 15 s sin posiciones.

## Pruebas

```bash
.venv/Scripts/python -m pytest        # 31 pruebas: validación, HTTP y WebSocket contra un servidor real
```
