# Opcional: el gateway como contenedor (por ejemplo, junto a servicios que tambien corran como contenedores/pods).
# En la VM actual se usa systemd (deploy/gateway.service); el contenedor solo necesita las URL de los servicios:
#   docker build -t library-gateway services/gateway
#   docker run -p 127.0.0.1:8080:8080 -e AUTH_URL=http://servicio-login:5000 -e PEDIDOS_URL=http://servicio-pedidos:5004 ... library-gateway
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
RUN useradd -r -u 10001 gateway
USER gateway
EXPOSE 8080
# Dentro del contenedor hay que escuchar en 0.0.0.0; publica el puerto solo en loopback (-p 127.0.0.1:8080:8080).
CMD ["gunicorn", "-w", "1", "--threads", "200", "-b", "0.0.0.0:8080", "app:app"]
