import sys
import time
import tkinter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gps_app  # noqa: E402


class FakeSender:
    def __init__(self, url, on_status=lambda text: None):
        self.url, self.offered, self.stopped = url, [], False
        on_status("Conectado")

    def start(self):
        pass

    def offer(self, payload):
        self.offered.append(payload)

    def stop(self):
        self.stopped = True


@pytest.fixture(scope="module")
def window():
    """Una sola ventana Tk por módulo: iniciar y destruir varias en el mismo proceso falla de forma intermitente en Windows."""
    try:
        root = gps_app.GpsApp("ws://localhost:5900/ws?role=gps", 3, 0.1, 5.0)
    except tkinter.TclError as exc:
        pytest.skip(f"sin pantalla disponible: {exc}")
    root.update()
    yield root
    root.destroy()


@pytest.fixture
def app(window, monkeypatch):
    monkeypatch.setattr(gps_app, "Sender", FakeSender)
    window.url.set("ws://localhost:5900/ws?role=gps")
    window.count.set(3)
    window.interval.set(0.1)
    window.scale.set(5.0)
    window.last_positions = []
    window.status.set("Detenido")
    yield window
    window.stop()
    window.update()


def pump(window, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        window.update()
        time.sleep(0.01)


def test_start_publishes_every_vehicle_and_draws_them(app):
    app.start()
    pump(app, 0.5)
    sent = [p for batch in app.sender.offered for p in batch]       # cada envío es un LOTE (lista) de posiciones
    assert {p["vehicle_id"] for p in sent} == {"V001", "V002", "V003"}
    assert len(app.sender.offered) >= 3 and len(sent) >= 9          # varios ciclos × 3 vehículos
    assert all(len(batch) == 3 for batch in app.sender.offered)     # un mensaje por ciclo, no uno por vehículo
    assert all(p.get("street") for p in sent)                       # van por calles reales, con nombre
    assert app.real_routes and "REALES" in app.route_info
    assert len(app.table.get_children()) == 3
    drawn = len(app.canvas.find_withtag("vehicle"))
    assert drawn >= 3 * 3 and drawn % 3 == 0                # marcador (halo, cuerpo, flecha) y etiqueta por vehículo
    assert app.kpi_count.get() == "3" and float(app.kpi_avg.get()) > 0        # indicadores de la flota
    assert float(app.kpi_km.get()) > 0 and int(app.kpi_streets.get()) >= 1
    assert len(app.canvas.find_withtag("route")) > 0
    assert app.status.get() == "Conectado"


def test_stop_halts_publishing_and_releases_the_sender(app):
    app.start()
    pump(app, 0.3)
    sender = app.sender
    app.stop()
    count = len(sender.offered)
    pump(app, 0.4)
    assert sender.stopped and len(sender.offered) == count
    assert app.running is False


@pytest.mark.parametrize("field, value", [("url", "http://x"), ("url", "ws://h/ws?role=map"),
                                          ("count", 0), ("count", 101), ("interval", 0.01)])
def test_invalid_settings_do_not_start(app, field, value):
    getattr(app, field).set(value)
    app.start()
    assert app.running is False and app.sender is None
    assert app.status.get().startswith("Configuración inválida")
