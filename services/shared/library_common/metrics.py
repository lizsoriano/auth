"""Contadores en memoria con salida en formato de texto de Prometheus (sin dependencias extra)."""
import threading
from collections import defaultdict

# Contadores que siempre aparecen (en 0) para que /metrics tenga la misma forma desde el primer minuto.
KNOWN_COUNTERS = {
    "cache_hits_total": "Lecturas servidas desde la caché de Redis.",
    "cache_misses_total": "Lecturas que no estaban en caché y fueron a PostgreSQL.",
    "cache_errors_total": "Operaciones de caché que fallaron por Redis (la lectura siguió por PostgreSQL).",
    "cache_invalidations_total": "Claves de caché borradas tras una escritura.",
    "redis_errors_total": "Errores de conexión, timeout o autenticación con Redis.",
    "auth_ok_total": "Peticiones con JWT aceptado.",
    "auth_rejected_total": "Peticiones con JWT rechazado (etiqueta reason).",
    "lock_contention_total": "Candados de Redis que no se pudieron tomar.",
}


def _escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    def __init__(self, service):
        self.service = service
        self._lock = threading.Lock()
        self._counters = defaultdict(int)
        for name in KNOWN_COUNTERS:
            self._counters[(name, ())] = 0

    def inc(self, name, value=1, **labels):
        key = (name, tuple(sorted(labels.items())))
        with self._lock:
            self._counters[key] += value

    def get(self, name, **labels):
        with self._lock:
            return self._counters.get((name, tuple(sorted(labels.items()))), 0)

    def snapshot(self):
        with self._lock:
            return dict(self._counters)

    def render_prometheus(self):
        lines = []
        seen = set()
        for (name, labels), value in sorted(self.snapshot().items()):
            if name not in seen:
                seen.add(name)
                lines.append(f"# HELP {name} {KNOWN_COUNTERS.get(name, name)}")
                lines.append(f"# TYPE {name} counter")
            pairs = [("service", self.service), *labels]
            label_text = ",".join(f'{key}="{_escape(val)}"' for key, val in pairs)
            lines.append(f"{name}{{{label_text}}} {value}")
        return "\n".join(lines) + "\n"
