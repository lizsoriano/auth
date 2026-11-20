"""Identificar la calle de un punto con OpenStreetMap (Nominatim, geocodificación inversa).

Nominatim es gratuito pero con política de uso (https://operations.osmfoundation.org/policies/nominatim/):
máximo 1 petición por segundo, un User-Agent que identifique la aplicación y NO consultar en masa. Por eso:
  · se limita a 1 petición/segundo en todo el servicio,
  · se guarda en caché (puntos a ~10 m comparten respuesta),
  · solo se consulta cuando una persona hace clic en el mapa (nunca por cada posición de cada vehículo),
  · solo acepta puntos del área metropolitana de Monterrey.
Las calles de las rutas simuladas NO usan este servicio: vienen ya en el GeoJSON de las rutas (OSRM/OpenStreetMap).
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "library-gps-service/1.0 (proyecto escolar UDEM; ruth.soriano@udem.edu)"
# Área metropolitana de Monterrey (con margen): (lat_min, lat_max, lon_min, lon_max)
MONTERREY_BOX = (25.40, 26.00, -100.75, -99.95)
SOURCE = "Nominatim / OpenStreetMap"


class GeocodeError(RuntimeError):
    """El servicio externo no respondió o respondió algo inesperado."""


class OutOfAreaError(ValueError):
    """El punto está fuera del área de Monterrey o no es una coordenada válida."""


def fetch_json(url, timeout=8):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                   "Accept-Language": "es"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise GeocodeError(f"Nominatim no respondió: {exc}") from exc


class Geocoder:
    def __init__(self, fetch=fetch_json, min_interval=1.0, cache_size=512, clock=time.monotonic, sleep=time.sleep):
        self._fetch, self._min_interval = fetch, min_interval
        self._clock, self._sleep = clock, sleep
        self._cache = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        self._last_call = None
        self.requests_made = 0   # peticiones reales a Nominatim (las de caché no cuentan)

    @staticmethod
    def _check(lat, lon):
        for value in (lat, lon):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
                raise OutOfAreaError("lat y lon deben ser números")
        lat_min, lat_max, lon_min, lon_max = MONTERREY_BOX
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            raise OutOfAreaError("El punto está fuera del área metropolitana de Monterrey")

    def reverse(self, lat, lon):
        """Calle y colonia de un punto: {street, suburb, city, state, display_name, source, cached}."""
        self._check(lat, lon)
        key = (round(lat, 4), round(lon, 4))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return {**self._cache[key], "cached": True}
            if self._last_call is not None:                      # máximo 1 petición por segundo
                wait = self._min_interval - (self._clock() - self._last_call)
                if wait > 0:
                    self._sleep(wait)
            query = urllib.parse.urlencode({"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
                                            "zoom": 17, "addressdetails": 1, "accept-language": "es"})
            try:
                data = self._fetch(f"{NOMINATIM_URL}?{query}")
            finally:
                self._last_call = self._clock()
                self.requests_made += 1
            result = self._normalize(data)
            self._cache[key] = result
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return {**result, "cached": False}

    @staticmethod
    def _normalize(data):
        if not isinstance(data, dict) or "error" in data:
            raise GeocodeError("Nominatim no encontró una calle en ese punto")
        address = data.get("address") or {}
        street = address.get("road") or address.get("pedestrian") or address.get("highway") or data.get("name") or ""
        return {"street": street, "suburb": address.get("suburb") or address.get("neighbourhood") or "",
                "city": address.get("city") or address.get("town") or address.get("municipality") or "",
                "state": address.get("state") or "", "display_name": data.get("display_name", ""), "source": SOURCE}
