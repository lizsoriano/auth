"""GPSapp: aplicación de escritorio que simula vehículos moviéndose por las calles REALES de Monterrey y publica sus
posiciones por WebSocket (role=gps) al microservicio de rastreo.

  python gps_app.py                      # ventana Tkinter (3 vehículos por las calles reales de Monterrey)
  python gps_app.py --autostart          # la ventana empieza a simular sin pulsar «Iniciar»
  python gps_app.py --headless -n 3      # sin ventana, imprime calle y velocidad promedio de cada vehículo
  python gps_app.py -n 50                # 50 vehículos (hasta 100 desde la ventana, más en --headless)
  python gps_app.py --start-time 08:00   # hora simulada de inicio (hora pico, escolar, noche…)
  python gps_app.py --straight-lines     # circuitos antiguos en línea recta (sin GeoJSON)
  python routing.py --refresh            # vuelve a pedir las rutas reales a OSRM/OpenStreetMap
"""
import argparse
import math
import os
import queue
import sys
import time
import tkinter as tk
from tkinter import ttk

from sender import Sender
from simulator_core import DEFAULT_URL, ROUTES, Fleet, average_speed_kmh, batches, default_routes, load_hazards
from traffic import Hazard, signal_state

# Paleta inspirada en Google Maps
BLUE, BLUE_DARK, BLUE_SOFT = "#1a73e8", "#174ea6", "#e8f0fe"
GREEN, RED, AMBER = "#188038", "#d93025", "#e37400"
INK, MUTED, LINE, SURFACE, MAP_BG = "#202124", "#5f6368", "#dadce0", "#f1f3f4", "#e8eaed"
FONT, FONT_BOLD = ("Segoe UI", 10), ("Segoe UI", 10, "bold")
ROUTE_COLORS = ("#1a73e8", "#d93025", "#188038", "#f9ab00", "#9334e6", "#12b5cb")
MAX_VEHICLES_GUI = 100
PALETTE = ("#d93025", "#1a73e8", "#188038", "#b45309", "#9334e6", "#0e7490", "#be185d", "#4d7c0f", "#c2410c", "#334155")


HAZARD_STYLE = {"traffic_signals": ("#9aa0a6", 4), "crossing": ("#1a73e8", 2), "stop": ("#b31412", 3), "bump": ("#e37400", 3),
                "pothole": ("#5f6368", 2), "school": ("#188038", 4)}
SIGNAL_COLORS = {"green": "#34a853", "yellow": "#fbbc04", "red": "#ea4335", "flash": "#fbbc04", "idle": "#9aa0a6"}
DAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


class Projection:
    """Proyección equirrectangular de las rutas al tamaño actual del canvas."""

    def __init__(self, routes=ROUTES):
        points = [(p[1], p[2]) for route in routes for p in route.points]
        self.min_lat = min(p[0] for p in points)
        self.max_lat = max(p[0] for p in points)
        self.min_lon = min(p[1] for p in points)
        self.max_lon = max(p[1] for p in points)
        self.k = math.cos(math.radians((self.min_lat + self.max_lat) / 2))
        self.width = self.height = 1

    def resize(self, width, height):
        self.width, self.height = max(width, 50), max(height, 50)

    def xy(self, lat, lon, margin=44):
        span_x = (self.max_lon - self.min_lon) * self.k
        span_y = self.max_lat - self.min_lat
        scale = min((self.width - 2 * margin) / span_x, (self.height - 2 * margin) / span_y)
        x = (self.width - span_x * scale) / 2 + (lon - self.min_lon) * self.k * scale
        y = (self.height + span_y * scale) / 2 - (lat - self.min_lat) * scale
        return x, y


def status_color(text):
    """Color del indicador según el estado que reporta el emisor."""
    if text == "Conectado":
        return GREEN
    if text.startswith(("Sin conexión", "Conexión perdida", "Configuración inválida")):
        return RED
    if text.startswith("Conectando"):
        return AMBER
    return MUTED


class GpsApp(tk.Tk):
    def __init__(self, url, vehicles, interval, time_scale, routes=None, autostart=False, start_time=None, weekday=None):
        super().__init__()
        self.start_time, self.weekday = start_time, weekday
        self.title("GPSapp — Simulador de vehículos en Monterrey")
        self.geometry("1240x720")
        self.minsize(980, 560)
        self.configure(bg=SURFACE)
        self.routes = tuple(routes) if routes else default_routes()
        self.real_routes = any(route.closed for route in self.routes)
        self.projection = Projection(self.routes)
        self.fleet = None
        self.sender = None
        self.running = False
        self.status_queue = queue.Queue()
        self.last_positions = []
        self.hazard_points = self._hazard_points()

        self.url = tk.StringVar(value=url)
        self.count = tk.IntVar(value=vehicles)
        self.interval = tk.DoubleVar(value=interval)
        self.scale = tk.DoubleVar(value=time_scale)
        self.status = tk.StringVar(value="Detenido")
        self.route_info = ("Rutas REALES por las calles (GeoJSON de OSRM / OpenStreetMap)" if self.real_routes
                           else "Rutas en línea recta entre puntos (sin GeoJSON)")
        self._style()
        self._build()
        self.status.trace_add("write", lambda *_: self._paint_status())
        self._paint_status()
        self.after(200, self._poll_status)
        if autostart:
            self.after(400, self.start)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------ estilo
    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=FONT, background=SURFACE, foreground=INK)
        style.configure("TFrame", background=SURFACE)
        style.configure("Header.TFrame", background=BLUE)
        style.configure("Header.TLabel", background=BLUE, foreground="white", font=("Segoe UI", 15, "bold"))
        style.configure("HeaderSub.TLabel", background=BLUE, foreground="#d2e3fc", font=("Segoe UI", 9))
        style.configure("TLabel", background=SURFACE, foreground=INK)
        style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9, "bold"))
        style.configure("TEntry", fieldbackground="white", bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=5)
        style.configure("TSpinbox", fieldbackground="white", bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=4,
                        arrowsize=12)
        style.configure("TButton", padding=(14, 7), font=FONT_BOLD, background="white", foreground=BLUE,
                        bordercolor=LINE, lightcolor="white", darkcolor="white", focusthickness=0)
        style.map("TButton", background=[("active", BLUE_SOFT), ("disabled", SURFACE)], foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=BLUE, foreground="white", bordercolor=BLUE, lightcolor=BLUE, darkcolor=BLUE)
        style.map("Accent.TButton", background=[("active", BLUE_DARK), ("disabled", "#a8c7fa")], foreground=[("disabled", "white")])
        style.configure("Stop.TButton", background="white", foreground=RED, bordercolor=RED, lightcolor="white", darkcolor="white")
        style.map("Stop.TButton", background=[("active", "#fce8e6"), ("disabled", SURFACE)], foreground=[("disabled", MUTED)])
        style.configure("Treeview", font=FONT, rowheight=32, background="white", fieldbackground="white", foreground=INK,
                        bordercolor=LINE, lightcolor="white", darkcolor="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background=SURFACE, foreground=MUTED, relief="flat",
                        padding=(6, 8), bordercolor=LINE)
        style.map("Treeview", background=[("selected", BLUE_SOFT)], foreground=[("selected", INK)])
        style.map("Treeview.Heading", background=[("active", LINE)])

    def _hazard_points(self):
        """Señales viales únicas (el mismo semáforo puede estar en varias rutas) como (Hazard, kind)."""
        collection, seen, found = load_hazards(), set(), []
        for feature in (collection or {}).get("features", []):
            p = feature["properties"]
            lon, lat = feature["geometry"]["coordinates"]
            key = (p["kind"], lon, lat)
            if key in seen or p["kind"] not in HAZARD_STYLE:
                continue
            seen.add(key)
            props = {k: v for k, v in p.items() if k not in {"id", "kind", "source", "route", "along_m", "name"}}
            found.append(Hazard(p["id"], p["kind"], lat, lon, 0.0, props=props))
        return found

    def _card(self, parent, title):
        """Tarjeta de indicador (blanca, con borde fino) con un número grande y un título pequeño."""
        frame = tk.Frame(parent, bg="white", highlightbackground=LINE, highlightthickness=1, padx=14, pady=6)
        value = tk.StringVar(value="–")
        tk.Label(frame, textvariable=value, bg="white", fg=INK, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(frame, text=title, bg="white", fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        return frame, value

    # ------------------------------------------------------------------ UI
    def _build(self):
        header = ttk.Frame(self, style="Header.TFrame", padding=(18, 10))
        header.pack(fill="x")
        title = ttk.Frame(header, style="Header.TFrame")
        title.pack(side="left")
        ttk.Label(title, text="📍  GPSapp · Monterrey", style="Header.TLabel").pack(anchor="w")
        ttk.Label(title, text="Simulador de vehículos por las calles reales de OpenStreetMap", style="HeaderSub.TLabel").pack(anchor="w")
        self.status_chip = tk.Label(header, textvariable=self.status, font=FONT_BOLD, padx=14, pady=5, bd=0)
        self.status_chip.pack(side="right")

        bar = ttk.Frame(self, padding=(14, 12, 14, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Servidor").grid(row=0, column=0, sticky="w")
        self.url_entry = ttk.Entry(bar, textvariable=self.url, width=38)
        self.url_entry.grid(row=0, column=1, padx=(6, 16))
        ttk.Label(bar, text="Vehículos").grid(row=0, column=2)
        self.count_spin = ttk.Spinbox(bar, from_=1, to=MAX_VEHICLES_GUI, width=4, textvariable=self.count)
        self.count_spin.grid(row=0, column=3, padx=(6, 16))
        ttk.Label(bar, text="Envío cada (s)").grid(row=0, column=4)
        self.interval_spin = ttk.Spinbox(bar, from_=0.2, to=10, increment=0.2, width=5, textvariable=self.interval)
        self.interval_spin.grid(row=0, column=5, padx=(6, 16))
        ttk.Label(bar, text="Aceleración ×").grid(row=0, column=6)
        self.scale_spin = ttk.Spinbox(bar, from_=1, to=50, increment=1, width=4, textvariable=self.scale)
        self.scale_spin.grid(row=0, column=7, padx=(6, 18))
        self.start_button = ttk.Button(bar, text="▶  Iniciar", style="Accent.TButton", command=self.start)
        self.start_button.grid(row=0, column=8, padx=3)
        self.stop_button = ttk.Button(bar, text="■  Detener", style="Stop.TButton", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=9, padx=3)

        kpis = ttk.Frame(self, padding=(14, 6, 14, 6))
        kpis.pack(fill="x")
        for column, (title, attr) in enumerate((("vehículos en ruta", "kpi_count"), ("km/h promedio de la flota", "kpi_avg"),
                                                ("km recorridos en total", "kpi_km"), ("calles distintas recorridas", "kpi_streets"),
                                                ("hora simulada", "kpi_clock"))):
            card, value = self._card(kpis, title)
            card.grid(row=0, column=column, padx=(0, 10), sticky="w")
            setattr(self, attr, value)
        self.info_text = tk.StringVar(value=self.route_info)
        ttk.Label(kpis, textvariable=self.info_text, style="Muted.TLabel", wraplength=330,
                  foreground=GREEN if self.real_routes else AMBER).grid(row=0, column=5, padx=(10, 0), sticky="w")

        body = ttk.Frame(self, padding=(14, 0, 14, 8))
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=MAP_BG, highlightthickness=1, highlightbackground=LINE)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)

        side = tk.Frame(body, bg="white", highlightbackground=LINE, highlightthickness=1)
        side.pack(side="left", fill="y", padx=(10, 0))
        ttk.Label(side, text="VEHÍCULOS", style="Panel.TLabel", padding=(12, 10, 12, 4)).pack(anchor="w")
        columns = ("id", "calle", "evento", "vel", "prom", "km")
        self.table = ttk.Treeview(side, columns=columns, show="headings", height=12)
        for name, title, width in (("id", "Vehículo", 66), ("calle", "Calle (OpenStreetMap)", 150), ("evento", "Qué pasa", 170),
                                   ("vel", "km/h", 48),
                                   ("prom", "Prom.", 56), ("km", "Km", 56)):
            self.table.heading(name, text=title)
            self.table.column(name, width=width, anchor="w" if name in ("calle", "evento") else "center")
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        ttk.Label(self, text="Mapa y rutas © colaboradores de OpenStreetMap (ODbL) · rutas calculadas con OSRM · "
                             "velocidad promedio = distancia total ÷ tiempo total", style="Muted.TLabel",
                  padding=(16, 0, 16, 8)).pack(fill="x")

    def _paint_status(self):
        color = status_color(self.status.get())
        self.status_chip.configure(bg="white", fg=color)

    def _on_resize(self, event):
        self.projection.resize(event.width, event.height)
        self._draw_routes()
        self._draw_vehicles()

    def _draw_routes(self):
        canvas, proj = self.canvas, self.projection
        canvas.delete("route")
        for step in range(1, 12):     # cuadrícula tenue: da sensación de mapa
            x, y = proj.width * step / 12, proj.height * step / 12
            canvas.create_line(x, 0, x, proj.height, fill="#dfe1e5", tags="route")
            canvas.create_line(0, y, proj.width, y, fill="#dfe1e5", tags="route")
        for index, route in enumerate(self.routes):
            coords = [proj.xy(p[1], p[2]) for p in route.vertices()]
            flat = [c for xy in coords for c in xy]
            color = ROUTE_COLORS[index % len(ROUTE_COLORS)]
            if self.real_routes:       # como las indicaciones de Google Maps: borde blanco y encima el color
                canvas.create_line(*flat, fill="white", width=9, capstyle="round", joinstyle="round", tags="route")
                canvas.create_line(*flat, fill=color, width=5, capstyle="round", joinstyle="round", tags="route")
            else:
                canvas.create_line(*flat, fill="#9aa0a6", width=2, dash=(6, 4), tags="route")
        for route in self.routes:
            for (name, lat, lon) in (route.landmarks or route.points):
                if not name:
                    continue
                x, y = proj.xy(lat, lon)
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="white", outline="#5f6368", width=2, tags="route")
                for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):      # halo blanco para que el texto se lea sobre las rutas
                    canvas.create_text(x + 9 + dx, y - 9 + dy, text=name, anchor="w", fill="white",
                                       font=("Segoe UI", 9, "bold"), tags="route")
                canvas.create_text(x + 9, y - 9, text=name, anchor="w", fill="#3c4043", font=("Segoe UI", 9, "bold"), tags="route")

    def _draw_hazards(self):
        """Semáforos (con su luz de este instante), cruces, topes, baches y escuelas; se redibujan en cada ciclo."""
        canvas, proj = self.canvas, self.projection
        canvas.delete("hazard")
        clock = self.fleet.clock if self.fleet else None
        night = bool(clock and clock.schedule.is_night(clock.tod_s))
        for hazard in self.hazard_points:
            x, y = proj.xy(hazard.latitude, hazard.longitude)
            if not -10 < x < proj.width + 10 or not -10 < y < proj.height + 10:
                continue
            color, radius = HAZARD_STYLE[hazard.kind]
            if hazard.kind == "traffic_signals":
                state = signal_state(hazard, clock.tod_s, night) if clock else "idle"
                color = SIGNAL_COLORS[state]
            if hazard.kind == "school":
                canvas.create_rectangle(x - radius, y - radius, x + radius, y + radius, fill=color, outline="white", tags="hazard")
            else:
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="white", width=1, tags="hazard")

    def _draw_vehicles(self):
        canvas = self.canvas
        self._draw_hazards()
        canvas.delete("vehicle")
        for index, position in enumerate(self.last_positions):
            x, y = self.projection.xy(position["latitude"], position["longitude"])
            color = PALETTE[index % len(PALETTE)]
            angle = math.radians(position["heading"])
            canvas.create_oval(x - 17, y - 17, x + 17, y + 17, fill=color, outline="", stipple="gray25", tags="vehicle")   # halo
            canvas.create_oval(x - 12, y - 12, x + 12, y + 12, fill=color, outline="white", width=3, tags="vehicle")       # cuerpo
            tip = (x + 8 * math.sin(angle), y - 8 * math.cos(angle))
            left = (x + 6 * math.sin(angle + 2.4), y - 6 * math.cos(angle + 2.4))
            right = (x + 6 * math.sin(angle - 2.4), y - 6 * math.cos(angle - 2.4))
            canvas.create_polygon(*tip, *left, *right, fill="white", outline="", tags="vehicle")                           # rumbo
            label = canvas.create_text(x + 24, y, text=position["vehicle_id"], anchor="w", fill=INK,
                                       font=("Segoe UI", 9, "bold"), tags="vehicle")
            x1, y1, x2, y2 = canvas.bbox(label)
            pill = canvas.create_rectangle(x1 - 6, y1 - 2, x2 + 6, y2 + 2, fill="white", outline=LINE, tags="vehicle")
            canvas.tag_lower(pill, label)

    def _refresh_table(self):
        self.table.delete(*self.table.get_children())
        for index, p in enumerate(self.last_positions):
            tag = f"v{index % len(PALETTE)}"
            self.table.tag_configure(tag, foreground=PALETTE[index % len(PALETTE)])
            self.table.insert("", "end", tags=(tag,), values=(p["vehicle_id"], p.get("street", "—"), p.get("event_text", "—"),
                                                              f'{p["speed"]:.0f}',
                                                              f'{p["avg_speed"]:.1f}', f'{p["trip_distance_m"] / 1000:.2f}'))

    def _refresh_kpis(self):
        positions = self.last_positions
        distance = sum(p["trip_distance_m"] for p in positions)
        seconds = sum(p["trip_time_s"] for p in positions)
        self.kpi_count.set(str(len(positions)))
        self.kpi_avg.set(f"{average_speed_kmh(distance, seconds):.1f}" if seconds > 0 else "–")   # Σd / Σt de toda la flota
        self.kpi_km.set(f"{distance / 1000:.1f}")
        self.kpi_streets.set(str(len({p["street"] for p in positions if p.get("street")})))
        clock = self.fleet.clock
        self.kpi_clock.set(f"{clock.text} · {DAY_NAMES[clock.weekday]}")
        self.info_text.set(f"{self.route_info}\n{clock.status()}")

    # ------------------------------------------------------------ control
    def _read_settings(self):
        count, interval, scale = int(self.count.get()), float(self.interval.get()), float(self.scale.get())
        if not 1 <= count <= MAX_VEHICLES_GUI or not 0.1 <= interval <= 30 or not 1 <= scale <= 100:
            raise ValueError(f"Vehículos 1-{MAX_VEHICLES_GUI}, intervalo 0.1-30 s, aceleración 1-100")
        url = self.url.get().strip()
        if not url.startswith(("ws://", "wss://")) or "role=gps" not in url:
            raise ValueError("La URL debe ser ws://host:puerto/ws?role=gps")
        return url, count, interval, scale

    def start(self):
        try:
            url, count, interval, scale = self._read_settings()
        except (ValueError, tk.TclError) as exc:
            self.status.set(f"Configuración inválida: {exc}")
            return
        self.fleet = Fleet(count, time_scale=scale, routes=self.routes, start_time=self.start_time, weekday=self.weekday)
        self.sender = Sender(url, on_status=self.status_queue.put)
        self.sender.start()
        self.running = True
        self.interval_s = interval
        for widget in (self.start_button, self.url_entry, self.count_spin, self.interval_spin, self.scale_spin):
            widget.state(["disabled"])
        self.stop_button.state(["!disabled"])
        self._tick()

    def stop(self):
        self.running = False
        if self.sender:
            self.sender.stop()
            self.sender = None
        for widget in (self.start_button, self.url_entry, self.count_spin, self.interval_spin, self.scale_spin):
            widget.state(["!disabled"])
        self.stop_button.state(["disabled"])

    def _tick(self):
        if not self.running:
            return
        positions = self.fleet.step(self.interval_s)
        for batch in batches(positions):      # un mensaje por lote de hasta 100 vehículos
            self.sender.offer(batch)
        self.last_positions = positions
        self._draw_vehicles()
        self._refresh_table()
        self._refresh_kpis()
        self.after(int(self.interval_s * 1000), self._tick)

    def _poll_status(self):
        try:
            while True:
                self.status.set(self.status_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(200, self._poll_status)

    def _close(self):
        self.stop()
        self.destroy()


def run_headless(url, vehicles, interval, time_scale, duration, routes=None, start_time=None, weekday=None):
    fleet = Fleet(vehicles, time_scale=time_scale, routes=routes, start_time=start_time, weekday=weekday)
    print(f"{len(fleet.routes)} rutas, {sum(len(r.points) for r in fleet.routes)} vértices "
          f"({'reales por las calles' if any(r.closed for r in fleet.routes) else 'en línea recta'})", flush=True)
    sender = Sender(url, on_status=lambda text: print(f"[estado] {text}", flush=True))
    sender.start()
    deadline = time.monotonic() + duration if duration else None
    try:
        while deadline is None or time.monotonic() < deadline:
            positions = fleet.step(interval)
            for batch in batches(positions):
                sender.offer(batch)
            for position in positions[:12]:           # en consola solo los primeros: con cientos no tiene caso imprimirlos
                print(f'{position["vehicle_id"]}  {position["latitude"]:.5f}, {position["longitude"]:.5f}  '
                      f'{position["speed"]:5.1f} km/h  prom {position["avg_speed"]:5.1f}  '
                      f'{position.get("street", "—")}  [{position["sim_time"]}] {position["event_text"]}', flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sender.stop()
        sender.join(timeout=3)
    print(f"Mensajes enviados: {sender.sent}")


def main():
    parser = argparse.ArgumentParser(description="Simulador de vehículos GPS en Monterrey")
    parser.add_argument("--url", default=os.getenv("GPS_URL", DEFAULT_URL))
    parser.add_argument("-n", "--vehicles", type=int, default=3)
    parser.add_argument("--interval", type=float, default=1.0, help="segundos entre envíos")
    parser.add_argument("--time-scale", type=float, default=5.0, help="aceleración del movimiento")
    parser.add_argument("--headless", action="store_true", help="sin ventana, imprime en consola")
    parser.add_argument("--duration", type=float, default=0, help="solo headless: segundos a correr (0 = sin fin)")
    parser.add_argument("--autostart", action="store_true", help="la ventana empieza a simular sin pulsar «Iniciar»")
    parser.add_argument("--start-time", metavar="HH:MM", help="hora simulada de inicio (por omisión, la hora actual de Monterrey)")
    parser.add_argument("--weekday", type=int, choices=range(7), metavar="0-6", help="día simulado: 0 = lunes … 6 = domingo")
    parser.add_argument("--straight-lines", action="store_true", help="circuitos en línea recta en vez de las calles reales")
    parser.add_argument("--refresh-routes", action="store_true", help="pide las rutas a OSRM/OpenStreetMap y termina")
    args = parser.parse_args()
    if args.refresh_routes:
        import routing
        return routing.main(["--refresh"])
    routes = ROUTES if args.straight_lines else None
    if args.headless:
        run_headless(args.url, args.vehicles, args.interval, args.time_scale, args.duration, routes, args.start_time, args.weekday)
    else:
        GpsApp(args.url, args.vehicles, args.interval, args.time_scale, routes, autostart=args.autostart,
               start_time=args.start_time, weekday=args.weekday).mainloop()


if __name__ == "__main__":
    sys.exit(main())
