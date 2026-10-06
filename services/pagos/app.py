"""Microservicio Pagos (puerto 5005): registra pagos y actualiza el estado de los pedidos.

Arrancar: python app.py   (desarrollo)   ·   gunicorn -b 127.0.0.1:5005 app:app   (producción, ver deploy/)
"""
from pagos_service import create_app

app = create_app()

if __name__ == "__main__":
    settings = app.extensions["settings"]
    app.run(host=settings.host, port=settings.port)
