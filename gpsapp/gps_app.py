"""GPSapp: aplicación de escritorio que simula vehículos moviéndose por Monterrey y publica sus
posiciones por WebSocket (role=gps) al microservicio de rastreo.

  python gps_app.py                      # ventana Tkinter
  python gps_app.py --headless -n 4      # sin ventana, imprime lo que envía
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
from simulator_core import DEFAULT_URL, ROUTES, Fleet

PALETTE = ("#d62828", "#1d4ed8", "#15803d", "#b45309", "#7c3aed", "#0e7490", "#be185d", "#4d7c0f", "#c2410c", "#334155")


class Projection:
    """Proyección equirrectangular de las rutas al tamaño actual del canvas."""

    def __init__(self):
        points = [(p[1], p[2]) for route in ROUTES for p in route.points]
        self.min_lat = min(p[0] for p in points)
        self.max_lat = max(p[0] for p in points)
        self.min_lon = min(p[1] for p in points)
        self.max_lon = max(p[1] for p in points)
        self.k = math.cos(math.radians((self.min_lat + self.max_lat) / 2))
        self.width = self.height = 1

    def resize(self, width, height):
        self.width, self.height = max(width, 50), max(height, 50)

    def xy(self, lat, lon, margin=40):
        span_x = (self.max_lon - self.min_lon) * self.k
        span_y = self.max_lat - self.min_lat
        scale = min((self.width - 2 * margin) / span_x, (self.height - 2 * margin) / span_y)
        x = (self.width - span_x * scale) / 2 + (lon - self.min_lon) * self.k * scale
        y = (self.height + span_y * scale) / 2 - (lat - self.min_lat) * scale
        return x, y


class GpsApp(tk.Tk):
    def __init__(self, url, vehicles, interval, time_scale):
        super().__init__()
        self.title("GPSapp — Simulador de vehículos en Monterrey")
        self.geometry("1040x660")
        self.minsize(820, 520)
        self.projection = Projection()
        self.fleet = None
        self.sender = None
        self.running = False
        self.status_queue = queue.Queue()
        self.last_positions = []

        self.url = tk.StringVar(value=url)
        self.count = tk.IntVar(value=vehicles)
        self.interval = tk.DoubleVar(value=interval)
        self.scale = tk.DoubleVar(value=time_scale)
        self.status = tk.StringVar(value="Detenido")
        self._build()
        self.after(200, self._poll_status)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------------ UI
    def _build(self):
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text="Servidor").grid(row=0, column=0, sticky="w")
        self.url_entry = ttk.Entry(bar, textvariable=self.url, width=42)
        self.url_entry.grid(row=0, column=1, padx=(4, 14))
        ttk.Label(bar, text="Vehículos").grid(row=0, column=2)
        self.count_spin = ttk.Spinbox(bar, from_=1, to=10, width=4, textvariable=self.count)
        self.count_spin.grid(row=0, column=3, padx=(4, 14))
        ttk.Label(bar, text="Envío cada (s)").grid(row=0, column=4)
        self.interval_spin = ttk.Spinbox(bar, from_=0.2, to=10, increment=0.2, width=5, textvariable=self.interval)
        self.interval_spin.grid(row=0, column=5, padx=(4, 14))
        ttk.Label(bar, text="Aceleración ×").grid(row=0, column=6)
        self.scale_spin = ttk.Spinbox(bar, from_=1, to=50, increment=1, width=4, textvariable=self.scale)
        self.scale_spin.grid(row=0, column=7, padx=(4, 14))
        self.start_button = ttk.Button(bar, text="Iniciar", command=self.start)
        self.start_button.grid(row=0, column=8, padx=2)
        self.stop_button = ttk.Button(bar, text="Detener", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=9, padx=2)

        ttk.Label(self, textvariable=self.status, padding=(10, 0, 10, 6)).pack(fill="x")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.canvas = tk.Canvas(body, bg="#eef2f9", highlightthickness=1, highlightbackground="#c9d3e8")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)

        columns = ("id", "lat", "lon", "vel", "rumbo")
        self.table = ttk.Treeview(body, columns=columns, show="headings", height=12)
        for name, title, width in (("id", "Vehículo", 70), ("lat", "Latitud", 80), ("lon", "Longitud", 90),
                                   ("vel", "km/h", 50), ("rumbo", "Rumbo", 55)):
            self.table.heading(name, text=title)
            self.table.column(name, width=width, anchor="center")
        self.table.pack(side="left", fill="y", padx=(8, 0))

    def _on_resize(self, event):
        self.projection.resize(event.width, event.height)
        self._draw_routes()
        self._draw_vehicles()

    def _draw_routes(self):
        canvas, proj = self.canvas, self.projection
        canvas.delete("route")
        for route in ROUTES:
            coords = [proj.xy(p[1], p[2]) for p in route.points]
            flat = [c for xy in coords + coords[:1] for c in xy]
            canvas.create_line(*flat, fill="#9aa9cf", width=2, dash=(6, 4), tags="route")
            for (name, lat, lon) in route.points:
                x, y = proj.xy(lat, lon)
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#5b6784", outline="", tags="route")
                canvas.create_text(x + 6, y - 8, text=name, anchor="w", fill="#5b6784", font=("Segoe UI", 8), tags="route")

    def _draw_vehicles(self):
        canvas = self.canvas
        canvas.delete("vehicle")
        for index, position in enumerate(self.last_positions):
            x, y = self.projection.xy(position["latitude"], position["longitude"])
            color = PALETTE[index % len(PALETTE)]
            angle = math.radians(position["heading"])
            tip = (x + 11 * math.sin(angle), y - 11 * math.cos(angle))
            left = (x + 7 * math.sin(angle + 2.5), y - 7 * math.cos(angle + 2.5))
            right = (x + 7 * math.sin(angle - 2.5), y - 7 * math.cos(angle - 2.5))
            canvas.create_polygon(*tip, *left, *right, fill=color, outline="white", width=1.5, tags="vehicle")
            canvas.create_text(x + 12, y + 10, text=position["vehicle_id"], anchor="w", fill=color,
                               font=("Segoe UI", 9, "bold"), tags="vehicle")

    def _refresh_table(self):
        self.table.delete(*self.table.get_children())
        for p in self.last_positions:
            self.table.insert("", "end", values=(p["vehicle_id"], f'{p["latitude"]:.5f}', f'{p["longitude"]:.5f}',
                                                 f'{p["speed"]:.0f}', f'{p["heading"]:.0f}°'))

    # ------------------------------------------------------------ control
    def _read_settings(self):
        count, interval, scale = int(self.count.get()), float(self.interval.get()), float(self.scale.get())
        if not 1 <= count <= 10 or not 0.1 <= interval <= 30 or not 1 <= scale <= 100:
            raise ValueError("Vehículos 1-10, intervalo 0.1-30 s, aceleración 1-100")
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
        self.fleet = Fleet(count, time_scale=scale)
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
        for position in positions:
            self.sender.offer(position)
        self.last_positions = positions
        self._draw_vehicles()
        self._refresh_table()
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


def run_headless(url, vehicles, interval, time_scale, duration):
    fleet = Fleet(vehicles, time_scale=time_scale)
    sender = Sender(url, on_status=lambda text: print(f"[estado] {text}", flush=True))
    sender.start()
    deadline = time.monotonic() + duration if duration else None
    try:
        while deadline is None or time.monotonic() < deadline:
            for position in fleet.step(interval):
                sender.offer(position)
                print(f'{position["vehicle_id"]}  {position["latitude"]:.5f}, {position["longitude"]:.5f}  '
                      f'{position["speed"]:5.1f} km/h  rumbo {position["heading"]:5.1f}°', flush=True)
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
    parser.add_argument("-n", "--vehicles", type=int, default=4)
    parser.add_argument("--interval", type=float, default=1.0, help="segundos entre envíos")
    parser.add_argument("--time-scale", type=float, default=5.0, help="aceleración del movimiento")
    parser.add_argument("--headless", action="store_true", help="sin ventana, imprime en consola")
    parser.add_argument("--duration", type=float, default=0, help="solo headless: segundos a correr (0 = sin fin)")
    args = parser.parse_args()
    if args.headless:
        run_headless(args.url, args.vehicles, args.interval, args.time_scale, args.duration)
    else:
        GpsApp(args.url, args.vehicles, args.interval, args.time_scale).mainloop()


if __name__ == "__main__":
    sys.exit(main())
