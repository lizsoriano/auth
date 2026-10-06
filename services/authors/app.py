"""Microservicio Authors (puerto 5003): autores y sus relaciones con libros.

Arrancar: python app.py   (desarrollo)   ·   gunicorn -b 127.0.0.1:5003 app:app   (producción, ver deploy/)
"""
from authors_service import create_app

app = create_app()

if __name__ == "__main__":
    settings = app.extensions["settings"]
    app.run(host=settings.host, port=settings.port)
