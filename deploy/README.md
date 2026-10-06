# Despliegue en la VM

Scripts para CentOS Stream 10, ejecutados por SSH en la VM. El despliegue de microservicios necesita una base Library ya existente, el rol de login, Postfix cuando se use correo y `/opt/library_soap_service` configurado. No se ha ejecutado este despliegue nuevo en la VM; consulta [PENDIENTE.md](../PENDIENTE.md).

## Secuencia

```bash
cd /opt/auth
git pull
bash deploy/setup_microservices_vm.sh
bash deploy/setup_tls_vm.sh IP_O_NOMBRE_DE_LA_VM
# Solo en una ventana de pruebas: detiene y reinicia Redis.
bash deploy/evidencias_microservicios.sh
```

`setup_microservices_vm.sh` pide las contraseñas de postgres y library_user por teclado, respalda la base, aplica 006–011 y configura roles dedicados, Redis y los seis entornos. Genera/reutiliza contraseñas locales, comparte JWT_SECRET_KEY/REDIS_URL y deja .env con permisos 600. No publiques esos archivos. La migración 011 se ejecuta como postgres. Las verificaciones finales consultan /health; revisa cualquier aviso antes de continuar.

Redis usa requirepass, AOF y noeviction. Las units `login.service`, `soap.service`, `users.service`, `authors.service`, `pedidos.service`, `pagos.service` arrancan gunicorn en 127.0.0.1:5000–5005. Books conserva `/opt/library_soap_service`; la unit fuerza producción y desactiva debug. Revisa en la VM:

```bash
systemctl status login soap users authors pedidos pagos
systemctl cat soap
curl -fsS 'http://127.0.0.1:5001/health?format=json'
```

`nginx-microservices-proxy.conf` instala `/users/`, `/authors/`, `/pedidos/`, `/pagos/` y elimina el prefijo. `/soap/` está en `nginx-soap-proxy.conf`; `/auth/` y `/library/` deben estar en la configuración existente. Verifica con `sudo nginx -T` y no dupliques locations. Por ejemplo, `/authors/authors` apunta a `/authors` en el servicio. No expongas los puertos Flask en el firewall.

## TLS autofirmado

`setup_tls_vm.sh IP_O_NOMBRE` crea un certificado RSA de 365 días con SAN y clave privada de permisos 600 en `/etc/nginx/tls/library`. Reutiliza un certificado vigente que coincida con el nombre; si está vencido o el nombre cambia, se detiene para permitir una renovación deliberada. Instala un servidor 443 que incluye los proxies de `/etc/nginx/default.d/`. Valida nginx y restaura la configuración anterior si es rechazada. Conserva HTTP y no modifica el firewall de GCP ni firewalld.

Copia únicamente el certificado público `server.crt` al cliente e impórtalo en su almacén de confianza/Postman. Nunca copies la clave privada. Comprueba TLS con el certificado confiado:

```bash
curl --cacert server.crt 'https://IP_O_NOMBRE/soap/health?format=json'
```

El nombre o IP debe coincidir con el SAN. Si ya existe un servidor 443 para ese nombre, revisa y adapta su configuración antes de ejecutar el script.

## Pruebas y evidencia

`evidencias_microservicios.sh` realiza escrituras y una caída real de Redis; exige una ventana de pruebas y datos adecuados. La evidencia de VM sigue pendiente. Para reproducir localmente con PostgreSQL, Redis y los seis servicios: `bash e2e/run_local.sh`. Unitarias: `pytest` en cada carpeta; integración real exige TEST_DATABASE_URL.

## Scripts anteriores

- `setup_db_vm.sh`: migraciones iniciales de login con respaldo.
- `setup_gmail_relay_vm.sh`: Postfix/Gmail con contraseña de aplicación local.
- `setup_soap_and_nginx_vm.sh`: units y proxy inicial, requiere entornos existentes.
- `deploy_jwt.sh`: despliegue histórico del JWT anterior; usa JWT_SECRET. Para el esquema actual usa setup_microservices_vm.sh.
- `demo_json.sh` y `evidencias_vm.sh`: ejemplos y evidencia del flujo inicial de login.

No introduzcas tokens en argumentos compartidos ni adjuntes .env/logs con secretos al entregar evidencia.

## Copia local a Desktop\app

En PowerShell, `./deploy/sync_workspace.ps1` muestra los cambios; `./deploy/sync_workspace.ps1 -Apply` copia services, data, deploy, docs, e2e y documentación raíz. Respalda los archivos reemplazados bajo `.auth-sync-backups` en el destino, conserva los demás proyectos y excluye .env y entornos virtuales. No elimina archivos antiguos. `auth-service` es una copia histórica distinta y no se reemplaza.
