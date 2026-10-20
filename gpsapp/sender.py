"""Hilo que publica posiciones por WebSocket y se reconecta solo si el microservicio cae."""
import json
import queue
import threading

import websocket  # paquete websocket-client


class Sender(threading.Thread):
    def __init__(self, url, on_status=lambda text: None, max_pending=200):
        super().__init__(daemon=True)
        self.url = url
        self.on_status = on_status
        self.outbox = queue.Queue(maxsize=max_pending)
        self._stop_event = threading.Event()
        self.sent = 0

    def offer(self, payload):
        """Encola sin bloquear; con el servidor caído descarta lo más viejo en vez de crecer sin límite."""
        try:
            self.outbox.put_nowait(payload)
        except queue.Full:
            try:
                self.outbox.get_nowait()
            except queue.Empty:
                pass
            self.outbox.put_nowait(payload)

    def stop(self):
        self._stop_event.set()

    def run(self):
        backoff = 1.0
        while not self._stop_event.is_set():
            self.on_status("Conectando…")
            try:
                ws = websocket.create_connection(self.url, timeout=5)
            except Exception as exc:
                self.on_status(f"Sin conexión ({exc}). Reintentando…")
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 10.0)
                continue
            backoff = 1.0
            self.on_status("Conectado")
            try:
                self._pump(ws)
            except Exception as exc:
                self.on_status(f"Conexión perdida ({exc}). Reintentando…")
            finally:
                try:
                    ws.close()
                except Exception:
                    pass
        self.on_status("Detenido")

    def _pump(self, ws):
        while not self._stop_event.is_set():
            try:
                payload = self.outbox.get(timeout=0.5)
            except queue.Empty:
                continue
            ws.send(json.dumps(payload))
            self.sent += 1
