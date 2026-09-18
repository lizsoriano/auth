# auth — servicio de login y esquema de base de datos (Library)

Microservicio independiente de **registro, confirmación de correo (Postfix), login, sesión de 30 minutos y
logout**, con respuestas en **XML** (por defecto) o **JSON** (`?format=json`), y los cambios a la base de datos
`library_db` que necesita.

```
auth/
├── services/login/   # el microservicio (Flask + Psycopg 3 + PostgreSQL), puerto 5000 → ver su README
└── data/             # esquema canónico (schema.sql), migraciones, rollbacks y auditoría de la BD
```

- **Empieza aquí:** [`services/login/README.md`](services/login/README.md) (instalación, Postfix, endpoints, Postman).
- **Cambios a la base de datos:** [`data/README.md`](data/README.md). Son **solo aditivos**: no alteran books, Electron ni el monolito.
- **Swagger:** `http://<host>:5000/docs/` con el servicio en marcha.

Estructura pensada para un monorepo: este directorio puede vivir junto a `services/soap` (books) y `electron-catalog`.
