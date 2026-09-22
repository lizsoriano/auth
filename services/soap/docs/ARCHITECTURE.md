# Arquitectura — módulo SOAP de clasificación Cloud

Diagrama fuente: [`ARCHITECTURE_DIAGRAM.puml`](./ARCHITECTURE_DIAGRAM.puml)
(PlantUML). Este documento explica en prosa lo que el diagrama muestra;
si alguno de los dos contradice al otro, corrígelo aquí y regenera el
diagrama, no al revés.

## 1. Nota sobre el renderizado del diagrama

Este entorno de trabajo no tiene `plantuml`, `dot`/Graphviz ni ninguna
herramienta de renderizado instalada (`plantuml -version` y `dot -V`
devuelven *command not found*, verificado el 2026-09-03), así que
`ARCHITECTURE_DIAGRAM.puml` no se pudo compilar directamente. En vez de
eso se dibujó a mano el mismo contenido como
[`ARCHITECTURE_DIAGRAM.svg`](./ARCHITECTURE_DIAGRAM.svg) — SVG plano,
sin dependencias externas, que muestra las mismas cajas, roles de
PostgreSQL y fronteras de proceso que describe el `.puml`. Es la imagen
que usa el reporte publicado (`portafolio/ejercicio03/index.html`,
sección 2).

El `.puml` se conserva como fuente formal (UML de componentes) para quien
prefiera regenerarlo con herramientas propias:

- **VS Code**: extensión "PlantUML" (`jebbs.plantuml`), que renderiza en
  vivo y exporta a PNG/SVG (requiere Java + Graphviz instalados, o el
  modo de renderizado remoto de la extensión).
- **PlantUML localmente**: `java -jar plantuml.jar
  docs/ARCHITECTURE_DIAGRAM.puml` (requiere Java 8+; Graphviz sólo es
  necesario para algunos tipos de diagrama, no estrictamente para este,
  que es de componentes).
- **Servidor público de PlantUML**: pegar el contenido del `.puml` en
  `https://www.plantuml.com/plantuml/uml/` (opción rápida sin instalar
  nada, pero envía el contenido del diagrama —sin datos reales, sólo
  nombres de componentes— a un servicio externo).

Si `ARCHITECTURE_DIAGRAM.svg` se actualiza en el futuro (por ejemplo tras
un cambio real de arquitectura), edítese a mano junto con el `.puml` —
ambos deben describir la misma macro-arquitectura, no solo el `.puml`.

## 2. Vista general de la cadena de integración

```
Persona clasificadora
      │
      ▼
Aplicación de escritorio (cliente SOAP, Tkinter u otro)
      │  construye/parsea sobres SOAP a partir del WSDL
      ▼
HTTP POST /soap  (XML, SOAP 1.1, namespace urn:library-classifier)
      │
      ▼
Módulo SOAP Flask (library_soap_service/)
      │  soap/service.py → soap/security.py (sólo la operación protegida)
      │                  → soap/db.py (psycopg2, SQL parametrizado)
      ▼
PostgreSQL — library_db  (rol soap_service_user, mínimo privilegio)
```

En paralelo, sin ninguna relación de llamada directa:

```
Navegador (usuario administrativo/consulta)
      │
      ▼
Apache/NGINX (reverse proxy /library)
      │
      ▼
Monolito Node.js/Express (integracion02/apps/web-monolito)
      │  src/config/db.js (pool pg, SQL parametrizado, sp_*/triggers/vistas)
      ▼
PostgreSQL — library_db  (rol library_user, CRUD completo del catálogo)
```

Las dos cadenas convergen únicamente en la base de datos. No existe
ninguna llamada HTTP, RPC ni de otro tipo entre el módulo SOAP y el
monolito: cada uno es un proceso, un despliegue y una unidad de
responsabilidad separada que **desconoce la existencia del otro** en
tiempo de ejecución. El único punto de contacto es el esquema
`library_db` que ambos leen (y, cada uno en sus propias tablas, escriben).

## 3. Fronteras de responsabilidad — quién es dueño de qué

| Componente | Dueño / repositorio | Responsabilidad | Qué posee en `library_db` |
|---|---|---|---|
| Aplicación de escritorio (cliente SOAP) | Ejercicio SOAP, fuera de `library_soap_service/` | Interfaz para que una persona vea conceptos pendientes y registre su clasificación Cloud; construye y parsea sobres SOAP a partir del WSDL | Ninguna — no se conecta a PostgreSQL directamente, todo pasa por el módulo SOAP |
| Módulo SOAP (`library_soap_service/`) | Este proyecto | Expone las 4 operaciones del WSDL; valida entrada; hace upsert de clasificadores y registra clasificaciones dentro de una transacción; construye `SOAP Fault` en vez de errores genéricos | Dueño de `clasificadores`, `clasificaciones_cloud`, `clientes_servidos`, `soap_service_credenciales`. Sólo lectura (`SELECT`) de `books`, `categories`, `concepts`, `book_concepts` — tablas que **no** posee |
| Monolito Node.js (`integracion02/apps/web-monolito`) | Proyecto `integracion02` (no se modifica desde aquí) | CRUD administrativo completo del catálogo vía SSR (libros, autores, géneros, formatos, categorías, conceptos, imágenes, usuarios del sistema web) | Dueño real de `books`, `categories`, `concepts`, `book_concepts`, `authors`, `genres`, `formats`, `users`, `book_authors`, `book_genres`, `book_images` |
| PostgreSQL (`library_db`) | Infraestructura compartida, sin dueño de aplicación único | Persistencia única; aplica las reglas de integridad (constraints, roles, triggers) que cada aplicación no puede evadir | — |

Cada aplicación se conecta con su **propio rol** de mínimo privilegio:
`library_user` para el monolito (dueño operativo del catálogo, con CRUD
completo sobre sus tablas) y `soap_service_user` para el módulo SOAP
(sólo `SELECT` en las tablas del catálogo que no le pertenecen, y
`SELECT`/`INSERT`/`UPDATE` —nunca `DELETE`— en sus tablas propias; ver
`sql/soap_module.sql`, nota final de auditoría). Ningún rol es
superusuario ni comparte credenciales con el otro.

## 4. Por qué esto no es un acoplamiento de llamadas, pero sí un acoplamiento de esquema

Ninguna de las dos aplicaciones invoca a la otra por red: no hay
webhooks, no hay una API interna entre ellas. Sin embargo, **sí** existe
acoplamiento — a través del esquema de `library_db` que el módulo SOAP
lee sin ser su dueño. Si el monolito renombra o cambia el tipo de una
columna que el módulo SOAP consulta (por ejemplo `books.isbn`), el
módulo SOAP se rompe en tiempo de ejecución sin que el equipo que hizo el
cambio en `integracion02` tenga ninguna forma de saberlo de antemano. Este
riesgo se documenta con detalle, junto a su mitigación propuesta, en
`docs/WSDL_AUDIT.md` (riesgo R-02).

## 5. Config y puertos

- Monolito: puerto `3000` (según
  `integracion02/apps/web-monolito/.env.example`), detrás de
  Apache/NGINX bajo `/library`.
- Módulo SOAP: puerto `5000` (`SOAP_PORT` en `.env.example` de este
  proyecto), elegido explícitamente distinto al del monolito para poder
  correr ambos procesos en la misma máquina de desarrollo sin choque de
  puertos (ver `docs/CONTRATO_DISENO.md` §8).
- Ambos apuntan a la misma `DATABASE_URL`/`library_db`, cada uno con sus
  propias credenciales de rol.
