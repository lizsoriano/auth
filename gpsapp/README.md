# GPSapp — simulador de vehículos en Monterrey

Aplicación de escritorio (Python + Tkinter) que mueve vehículos por circuitos de la zona metropolitana de Monterrey y publica sus posiciones por WebSocket (`role=gps`) al microservicio [`services/gps`](../services/gps/README.md).

## Ejecutar

```bash
cd gpsapp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest   # Linux/macOS: .venv/bin/python
.venv/Scripts/python gps_app.py                                   # ventana Tkinter
.venv/Scripts/python gps_app.py --headless -n 4 --duration 10     # sin ventana
```

Antes levanta el microservicio (`services/gps`, puerto 5900) y abre <http://localhost:5900/> para ver el mapa.

En la ventana: servidor (por defecto `ws://localhost:5900/ws?role=gps`), número de vehículos (1–10), intervalo de envío y aceleración. El lienzo muestra las rutas y los vehículos; la tabla, lo último enviado. Si el servicio cae, la app se reconecta sola (espera 1 → 10 s) y descarta lo más viejo en vez de acumular sin límite.

## Cómo simula

- Cuatro circuitos cerrados entre puntos reales (Macroplaza, Fundidora, Tec, Obispado, San Pedro, Santa Catarina, Guadalupe, Estadio BBVA, Cumbres…). Los vehículos van **en línea recta entre puntos**, no por las calles.
- Velocidad entre 15 y 80 km/h con variación aleatoria; el rumbo sale del tramo que recorren.
- **Aceleración** (por defecto ×5): el movimiento se multiplica para que se note en el mapa sin esperar minutos; la velocidad reportada sigue siendo la "real".

## Archivos

| Archivo | Qué hace |
|---|---|
| `simulator_core.py` | rutas, física de movimiento y `Fleet`; sin dependencias |
| `sender.py` | hilo WebSocket con reconexión (`websocket-client`) |
| `gps_app.py` | ventana Tkinter y modo `--headless` |
| `tests/test_core.py` | 12 pruebas del simulador |
| `tests/test_gui_smoke.py` | la ventana con un emisor falso: publica, dibuja, se detiene y rechaza configuración inválida (se omite sin pantalla) |

```bash
.venv/Scripts/python -m pytest
```

La ventana también se probó de punta a punta contra el microservicio real (conectó y publicó); esa comprobación no es automática porque necesita el servicio corriendo.
