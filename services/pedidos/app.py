"""Microservicio Pedidos (puerto 5004): pedidos, líneas, stock y estados.

Arrancar: python app.py   (desarrollo)   ·   gunicorn -b 127.0.0.1:5004 app:app   (producción, ver deploy/)
"""
from pedidos_service import create_app

app = create_app()

if __name__ == "__main__":
    settings = app.extensions["settings"]
    app.run(host=settings.host, port=settings.port)
