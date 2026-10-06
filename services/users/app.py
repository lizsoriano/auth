"""Microservicio Users (puerto 5002): usuarios, roles, correos y contraseñas.

Arrancar: python app.py   (desarrollo)   ·   gunicorn -b 127.0.0.1:5002 app:app   (producción, ver deploy/)
"""
from users_service import create_app

app = create_app()

if __name__ == "__main__":
    settings = app.extensions["settings"]
    app.run(host=settings.host, port=settings.port)
