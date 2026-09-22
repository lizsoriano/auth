# auth — plataforma de librería en línea (Library)

Monorepo con los microservicios y apps de la plataforma. Todos comparten la base de datos PostgreSQL
`library_db`, desplegada en una VM (Google Cloud, CentOS Stream 10) con Nginx como único punto de entrada
público (puerto 80): cada servicio corre en `127.0.0.1` y Nginx lo expone bajo un prefijo (`/library`, `/soap`).

```
auth/
├── services/
│   ├── login/          # ★ Microservicio de autenticación: Flask + Psycopg 3 + PostgreSQL, puerto 5000,
│   │                     XML/JSON, confirmación de correo por Postfix, Swagger → ver su README
│   └── soap/            # Servicio books: SOAP + REST (/books, /concepts) — Flask, puerto 5001
├── electron-catalog/     # App de escritorio (Electron) que consume el servicio books
├── data/                 # Esquema canónico de la BD (schema.sql), migraciones, rollbacks y auditoría
└── deploy/               # Scripts y unidades systemd para desplegar todo en la VM
```

`services/soap` y `electron-catalog` tienen cada uno su propio repositorio de origen
(`ejercicio05-library-soap-rest`, `catalogo-libros-electron`); aquí se incluyen como copia de referencia para
tener todo el monorepo en un solo lugar versionado, junto al servicio `login` y a `data/`.

## Servicios y dónde viven

| Servicio | Puerto (loopback) | Expuesto en Nginx | Código |
|---|---|---|---|
| `login` | 5000 | *(sin publicar; usar túnel SSH)* | [`services/login`](services/login/README.md) |
| `soap` (books) | 5001 | `/soap/` → `/soap/books`, `/soap/wsdl`, `/soap/soap`, `/soap/concepts` | [`services/soap`](services/soap/README.md) |
| `web-monolito` (no incluido aquí) | 3000 | `/library/` | repo `IntegracionesLibrary` |

## Por dónde empezar

- **Login:** [`services/login/README.md`](services/login/README.md) — instalación, Postfix, endpoints, Postman.
- **Base de datos:** [`data/README.md`](data/README.md). Cambios **solo aditivos**: no alteran books, Electron
  ni el monolito.
- **Desplegar/reproducir en la VM:** [`deploy/README.md`](deploy/README.md) — de cero o para levantar de nuevo
  `login.service`, `soap.service` y el proxy de Nginx.
- **Swagger del login:** `http://<host>:5000/docs/` con el servicio en marcha.
- **Electron:** [`electron-catalog/README.md`](electron-catalog/README.md). El endpoint y la base de imágenes se
  configuran dentro de la app (⚙ Configuración) — apuntan a `http://<IP-de-la-VM>/soap/books` y
  `http://<IP-de-la-VM>/library`. La IP externa de la VM es efímera: cambia si se apaga y enciende.
