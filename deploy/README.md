# deploy/ — desplegar y reproducir la VM

Scripts y unidades systemd para levantar `login` y `soap` en la VM (Google Cloud, CentOS Stream 10) detrás de
Nginx. Se corren **en la VM**, por SSH; ninguno se ejecuta desde tu máquina local.

## Orden para una VM nueva

| # | Script | Qué hace | Pide contraseña de |
|---|---|---|---|
| 1 | `../data/migrations/000_create_login_role.sql` … `003_login_service_grants.sql` | Esquema de `library_db` para `login` (ver [`../data/README.md`](../data/README.md)) | `postgres`, `library_user` |
| 2 | `setup_db_vm.sh` | Alternativa al paso anterior: aplica las migraciones con respaldo automático y verificación antes/después | `postgres`, `library_user` |
| 3 | `setup_gmail_relay_vm.sh` | Configura Postfix para entregar correo por Gmail (puerto 587; Google Cloud bloquea el 25 saliente) | tu Gmail (contraseña de aplicación) |
| 4 | `setup_soap_and_nginx_vm.sh` | Instala `soap.service`, `login.service` y el proxy de Nginx `/soap` | ninguna (no toca la BD) |

`setup_soap_and_nginx_vm.sh` asume que `/opt/library_soap_service` (con su `.venv` y `.env`, ver
[`../services/soap/README.md`](../services/soap/README.md)) y `/opt/auth/services/login` (con su `.venv` y
`.env`) **ya existen**. No los crea ni instala sus dependencias — solo las unidades systemd y el `location` de
Nginx. Es **idempotente**: correrlo de nuevo no cambia nada si ya estaba aplicado.

## Unidades systemd (referencia de lo que ya corre en la VM)

- **`login.service`** — gunicorn, puerto 5000, solo loopback. Depende de Postfix (`Wants=postfix.service`) pero
  arranca aunque Postfix falle (el correo simplemente no sale).
- **`soap.service`** — servidor de desarrollo de Flask, puerto 5001, solo loopback. `Environment=SOAP_PORT=5001`
  sobreescribe el `5000` que trae `/opt/library_soap_service/.env` (ese archivo no se toca).
- **`nginx-soap-proxy.conf`** — se instala en `/etc/nginx/default.d/`, mismo patrón que el `library-proxy.conf`
  ya existente (Ejercicio Guiado 02) que expone el monolito bajo `/library`.

Ninguno de los dos servicios se expone directamente a Internet: solo Nginx escucha en el puerto 80 público
(regla de firewall `allow-library-http`); `login` ni siquiera está publicado ahí todavía (se usa con un túnel
SSH: `gcloud compute ssh maquina-02 ... -- -L 5050:localhost:5000`).

## Otros scripts

- **`demo_json.sh correo@gmail.com [TOKEN]`** — corre `curl` (health, registro, verificación, login, sesión,
  logout) mostrando cada JSON formateado. Pensado para ver el flujo completo en la terminal.
- **`evidencias_vm.sh 1|2|3|4|5 [correo]`** — comandos de evidencia para la entrega/documentación (formatos
  XML/JSON, validaciones, login/sesión/logout, base de datos, `pytest`).

## Notas

- La IP externa de la VM es **efímera**: cambia si se apaga y se enciende. Los scripts usan `127.0.0.1`/`localhost`
  para todo lo que corre en la propia VM, así que no dependen de ella.
- Nada de esto guarda contraseñas: `setup_db_vm.sh` y `setup_gmail_relay_vm.sh` las piden por teclado (no se
  muestran ni se escriben en ningún archivo del repo); `setup_soap_and_nginx_vm.sh` no necesita ninguna.
