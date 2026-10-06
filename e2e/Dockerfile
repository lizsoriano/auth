# Imagen de las pruebas de punta a punta: los 6 servicios en un solo contenedor (python:3.12) contra
# PostgreSQL y Redis REALES que arranca e2e/run_local.sh. Solo para pruebas locales.
FROM python:3.12-slim
RUN pip install --no-cache-dir Flask==3.0.3 Werkzeug==3.0.3 "bcrypt>=4.1,<6" PyJWT==2.9.0 redis==5.2.1 \
    Flask-Cors==4.0.1 "psycopg[binary]>=3.2.1,<3.3" psycopg2-binary==2.9.9 python-dotenv==1.0.1 \
    email-validator==2.2.0 flask-swagger-ui==5.32.15 cryptography==43.0.1 requests==2.32.3
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/work/shared
WORKDIR /work
