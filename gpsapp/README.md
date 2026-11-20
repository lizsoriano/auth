# GPSapp — simulador de vehículos por las calles reales de Monterrey

Aplicación de escritorio (Python + Tkinter) que mueve vehículos por **rutas reales de OpenStreetMap** en la zona metropolitana de Monterrey y publica sus posiciones por WebSocket (`role=gps`) al microservicio [`services/gps`](../services/gps/README.md). Ya no van en línea recta entre puntos: siguen las calles, con su nombre y su velocidad típica.

## Ejecutar

```bash
cd gpsapp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest   # Linux/macOS: .venv/bin/python
.venv/Scripts/python gps_app.py --autostart                       # ventana Tkinter: 3 vehículos y empieza sola
.venv/Scripts/python gps_app.py --headless -n 3 --duration 10     # sin ventana, imprime calle, velocidad promedio y evento
.venv/Scripts/python gps_app.py --autostart --start-time 08:00 --weekday 1   # arranca en hora pico escolar (martes 08:00)
.venv/Scripts/python gps_app.py -n 50                             # 50 vehículos (hasta 100 desde la ventana)
```

Antes levanta el microservicio (`services/gps`, puerto 5900) y abre <http://localhost:5900/> para ver el mapa.

En la ventana: servidor (por defecto `ws://localhost:5900/ws?role=gps`), número de vehículos (1–100), intervalo de envío y aceleración. Muestra cuatro indicadores de la flota (vehículos, **km/h promedio**, km recorridos y calles distintas), el mapa con las rutas y los vehículos, y una tabla con la calle de cada uno. Si el servicio cae, la app se reconecta sola (espera 1 → 10 s) y descarta lo más viejo en vez de acumular sin límite.

## Rutas reales: GeoJSON + OpenStreetMap + OSRM

1. Los cuatro circuitos se definen por puntos de paso con nombre (Macroplaza, Fundidora, Tec, Obispado, San Pedro, Santa Catarina, Guadalupe, Estadio BBVA, Cumbres…).
2. **OSRM** (motor de rutas gratuito que usa los datos de OpenStreetMap) calcula el camino **por las calles** entre esos puntos y devuelve una geometría **GeoJSON `LineString`** (cientos de vértices), el nombre de cada calle, su distancia y su velocidad típica.
3. `routing.py` guarda el resultado en [`data/rutas_monterrey.geojson`](data/rutas_monterrey.geojson) (una sola vez: el servidor público de OSRM es de demostración y no debe usarse en cada arranque). La simulación lee ese archivo, así que funciona **sin internet**.
4. Los tramos sin nombre en OpenStreetMap (enlaces, retornos) se describen con las calles que los rodean: «Enlace Avenida X → Avenida Y».

```bash
python routing.py --refresh        # vuelve a pedir las rutas a OSRM y reescribe los GeoJSON (gpsapp y servicio)
python gps_app.py --straight-lines # circuitos antiguos en línea recta, sin GeoJSON
```

| Ruta | Distancia | Tiempo típico | Calles distintas |
|---|---|---|---|
| Centro - Fundidora - Tec | 17.1 km | 26 min | 24 |
| Corredor poniente | 38.2 km | 48 min | 36 |
| Oriente | 21.3 km | 37 min | 28 |
| Norte - Cumbres | 24.8 km | 32 min | 19 |

## Cómo simula

- Cada vehículo recorre el circuito cerrado siguiendo los vértices de la calle, con el **rumbo** del tramo.
- La **velocidad de crucero** tiende a la típica de cada calle según OpenStreetMap (una vía rápida ≈ 80 km/h, una calle local ≈ 15–30), con variación de tráfico y según el horario; la real baja hasta 0 ante semáforos, peatones y altos (máximo 80 km/h).
- **Aceleración** (por defecto ×5): el movimiento y el tiempo se multiplican para que se note en el mapa sin esperar minutos; la velocidad reportada sigue siendo la «real».
- Los vehículos se reparten de forma pareja entre las 4 rutas y escalonados a lo largo de cada una: con **3 vehículos** cada uno va por una ruta distinta; con 100, unos 25 por ruta.

## Velocidad promedio

```
velocidad promedio = distancia total recorrida ÷ tiempo total empleado      v̄ = Σd / Σt
km/h = (metros ÷ segundos) × 3.6
```

**No** es el promedio de las velocidades instantáneas: si recorres 1 km a 20 km/h (180 s) y 1 km a 60 km/h (60 s), vas 2 km en 240 s = **30 km/h**, no 40. Cada vehículo lleva `trip_distance_m` y `trip_time_s` (en tiempo simulado, para que la aceleración no distorsione el resultado) y envía `avg_speed`; la ventana calcula igual la de toda la flota (Σ distancia ÷ Σ tiempo) y el servicio la calcula para el recorrido de cada vehículo (`/vehicles/<id>/track.geojson`). La distancia entre vértices usa la fórmula de **Haversine**.

## Semáforos, cruces peatonales, altos, topes, baches y horarios

Sobre las rutas hay **señales viales reales de OpenStreetMap** (consultadas una vez a la API gratuita **Overpass** con `hazards.py --refresh` y guardadas en [`data/senales_viales.geojson`](data/senales_viales.geojson)):

| Señal | Cantidad en las 4 rutas | Origen | Qué hace el vehículo |
|---|---|---|---|
| Semáforo | 77 | OpenStreetMap | frena y espera en rojo; el ciclo (verde → amarillo → rojo) sale del id del semáforo; de noche parpadea en amarillo y se pasa a ≤30 km/h |
| Cruce peatonal | 117 | OpenStreetMap | con cierta probabilidad hay peatones: se detiene 6–14 s y les cede el paso; si no, pasa a ≤35 km/h |
| Zona escolar | 14 | OpenStreetMap | en horario escolar baja a 20 km/h en 150 m a la redonda |
| Tope | 1 | OpenStreetMap (`traffic_calming`) | baja a 10 km/h |
| Alto | 0 en estas rutas | OpenStreetMap | se detiene 2–4 s |
| Bache | 57 | **simulado** (OpenStreetMap no los tiene) | baja a 28 / 20 / 12 km/h según severidad |

**Horarios** (hora de Monterrey, UTC−6; están en el mismo GeoJSON): hora pico de la mañana 07:00–09:30 (×0.60), de la comida 13:30–15:30 (×0.75) y de la tarde 17:30–20:00 (×0.55), solo entre semana; horario escolar 06:45–08:30 y 12:45–14:30; noche 23:00–05:00 (calles más libres, semáforos intermitentes y casi sin peatones). La simulación arranca con la hora real de Monterrey; con `--start-time HH:MM --weekday 0-6` (o `Fleet(start_time=…, weekday=…)`) se fija otra hora para ver cada caso. El reloj avanza con la aceleración.

**Cómo frena**: mira hasta 220 m adelante y limita su velocidad con la curva de frenado `v = √(v_f² + 2·a·d)` (a = 2 m/s²) hasta la señal; nunca cruza la línea de alto mientras deba detenerse. Un semáforo en verde se pasa; si estará en rojo cuando llegue, ya viene frenando; si está en amarillo y no alcanza a detenerse, lo cruza. Cada posición lleva `event` (`traffic_signals`, `crossing`, `stop`, `bump`, `pothole`, `school`, `rush`, `night`, `clear`), `event_text` (por ejemplo «Esperando semáforo en rojo»), `sim_time` y `sim_day`.

Como los vehículos ahora **se detienen**, la velocidad promedio (Σd ÷ Σt) incluye las esperas: en pruebas, ≈ 22 km/h en hora pico y ≈ 43 km/h de madrugada sobre las mismas calles. Esa es justo la diferencia entre la velocidad promedio y la instantánea.

```bash
python hazards.py --refresh    # vuelve a pedir las señales a Overpass (reintenta si el servidor público está saturado)
```

## Servicios gratuitos que se pueden usar

| Servicio | Para qué | Cómo se usa aquí |
|---|---|---|
| **Mosaicos de OpenStreetMap** | dibujar el mapa | Leaflet en el mapa web (uso ligero, con atribución) |
| **OSRM** | rutas por las calles en GeoJSON, con nombres de calle | `routing.py` (una vez, con caché en archivo) |
| **Nominatim** | calle de un punto (geocodificación inversa) | endpoint `/geocode/reverse` del servicio, a 1 petición/segundo y con caché |
| **Overpass API** | semáforos, cruces, altos, topes y escuelas de OpenStreetMap | `hazards.py --refresh`, una vez y con reintentos (el servidor público a veces responde 502); la simulación lee el archivo y funciona sin internet |
| Alternativas | OpenRouteService (clave gratuita), Valhalla, GraphHopper | mismo patrón: pedir la ruta una vez y guardarla en GeoJSON |

Para uso intensivo, OSRM se puede **autoalojar** con Docker usando el extracto de México de Geofabrik, sin límites del servidor público.

## Escalabilidad

- La ventana y el modo `--headless` envían **un mensaje por ciclo** (lotes de hasta 100 vehículos), no uno por vehículo.
- El servicio difunde cada lote como **un solo mensaje GeoJSON** a los mapas.
- Medido en las pruebas: una flota de 500 vehículos avanza 10 pasos en menos de 2 s; el servicio recibe 100 vehículos × 5 lotes en menos de 3 s.
- Límite de la ventana: 100 vehículos (el lienzo y la tabla se redibujan en cada ciclo); en `--headless` no hay tope.

## Archivos

| Archivo | Qué hace |
|---|---|
| `simulator_core.py` | rutas, física de movimiento, velocidad promedio, `Fleet` y lotes; sin dependencias |
| `traffic.py` | tipos de señal, horarios, fases del semáforo y curva de frenado (solo biblioteca estándar) |
| `hazards.py` | pide a Overpass las señales viales, las pega a cada ruta y agrega los baches simulados |
| `data/senales_viales.geojson` | 266 señales sobre las rutas + horarios |
| `routing.py` | pide las rutas a OSRM y las convierte a GeoJSON (solo biblioteca estándar) |
| `data/rutas_monterrey.geojson` | las 4 rutas reales por las calles |
| `sender.py` | hilo WebSocket con reconexión (`websocket-client`) |
| `gps_app.py` | ventana Tkinter (diseño tipo Google Maps) y modo `--headless` |
| `tests/test_core.py` | pruebas del simulador: fórmula de velocidad promedio, calles, 3 carros, posiciones sobre las calles (< 2 m), 500 vehículos, paradas en semáforos/peatones, fases del semáforo, horarios que cruzan la medianoche, hora pico vs noche |
| `tests/test_routing.py` | conversión de OSRM a GeoJSON (con respuesta simulada), calles sin nombre y validez de los archivos incluidos |
| `tests/test_gui_smoke.py` | la ventana con un emisor falso: publica lotes, dibuja, calcula indicadores y rechaza configuración inválida (se omite sin pantalla) |

```bash
.venv/Scripts/python -m pytest        # 59 pruebas
```

La ventana también se probó de punta a punta contra el microservicio real (conectó y publicó 3 vehículos por calles reales); esa comprobación no es automática porque necesita el servicio corriendo.

Datos de rutas y calles © colaboradores de OpenStreetMap (licencia ODbL): <https://www.openstreetmap.org/copyright>.
