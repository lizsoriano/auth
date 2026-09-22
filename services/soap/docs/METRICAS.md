# Métricas técnicas (Tarea 5, trabajo en casa)

Para comparar contra REST en la siguiente sesión de la materia. Todo
medido de verdad (no estimado) el 2026-09-03, contra la implementación
final del módulo — ver `docs/EVIDENCIA_DESPLIEGUE_REAL.md` para el
contexto de dónde se corrió.

## Líneas de código

| Componente | Líneas | Comando |
|---|---|---|
| Núcleo del servicio (`app.py` + `soap/` + `db/` + `config/`) | 935 | `find app.py soap db config -name "*.py" \| xargs wc -l` |
| Cliente de escritorio (`soap_client.py`) | 361 | `wc -l soap_client.py` |
| WSDL/XSD (`wsdl/library-classifier.wsdl`) | 258 | `wc -l wsdl/library-classifier.wsdl` |
| SQL propio (`sql/soap_module.sql`) | 368 | `wc -l sql/soap_module.sql` |

Nota sobre la evolución de estas dos últimas cifras (ED-11, migración a
Stored Procedures/Vistas): el núcleo del servicio en Python **bajó** de
999 a 935 líneas (`db/repository.py` se simplificó al delegar los `JOIN`
y la transacción a PL/pgSQL), mientras que el SQL propio **subió** de
183 a 368 líneas (ahí es donde quedó ahora esa lógica). El total de
lógica no desapareció, se movió de capa — un dato concreto para
comparar contra REST, donde ese mismo trade-off (lógica en el
servidor de aplicación vs. en la base de datos) también aplica.

## Tamaño de mensajes reales

Solicitud `RegistrarClasificacion` real, capturada de verdad contra el
servicio (no un ejemplo escrito a mano):

```xml
<?xml version='1.0' encoding='utf-8'?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tns="urn:library-classifier"><soap:Body><tns:RegistrarClasificacionRequest><nombre>Metricas</nombre><apellidos>Prueba</apellidos><correo>metricas.1788460472@example.com</correo><bookId>6</bookId><conceptoId>18</conceptoId><modeloCloud>IaaS</modeloCloud><tipoCliente>medicion-metricas</tipoCliente></tns:RegistrarClasificacionRequest></soap:Body></soap:Envelope>
```

| Métrica | Valor |
|---|---|
| Bytes totales de la solicitud | 476 |
| Bytes de datos de negocio puros (solo los valores: nombre, apellidos, correo, bookId, conceptoId, modeloCloud, tipoCliente, sin tags) | 69 |
| Bytes de estructura XML (Envelope, Body, namespaces, tags de apertura/cierre) | 407 |
| **% que es estructura XML** | **85.5%** |
| **% que es dato de negocio real** | **14.5%** |

La respuesta exitosa correspondiente (`RegistrarClasificacionResponse`,
capturada en la misma corrida) tiene 4 campos de salida
(`clasificacionId`, `modeloCloud`, `clasificadoEn`, `mensaje`) con un
overhead de estructura similar, proporcionalmente mayor aún en
operaciones con más ida y vuelta de metadatos SOAP (Header WS-Security
en `ObtenerEstadisticasPorModelo`, que agrega ~300 bytes adicionales de
`wsse:Security`/`wsu:Created`/`wsse:Nonce` sin que ningún dato de
negocio adicional viaje en ellos).

## Tiempo de desarrollo

**Tiempo aproximado registrado por el estudiante: dos semanas**, desde el
diseño del contrato (WSDL + XSD + SQL + documento de decisiones) hasta el
despliegue y las pruebas end-to-end contra PostgreSQL/GCP reales,
incluyendo la corrección de los dos bugs reales encontrados en el camino
(esquema de WS-Security y namespaces XML — ver
`docs/EVIDENCIA_DESPLIEGUE_REAL.md` §2 y §5).

## Reflexión (preguntas del enunciado)

- **¿Qué pasaría si agregas un campo obligatorio a `RegistrarClasificacion`
  sin actualizar a los clientes?** Todo cliente existente (manual o
  generado por WSDL) empezaría a recibir `ValidacionFallida` en cada
  llamada, porque el campo nuevo llegaría vacío/ausente — SOAP con XSD
  fuerza a versionar el contrato explícitamente (un nuevo `minOccurs="0"`
  o una nueva operación) en vez de romper en silencio.
- **¿Qué partes del Envelope fueron boilerplate y cuáles dependieron de
  la operación?** `soap:Envelope`, `soap:Body`, los namespaces y el
  elemento raíz calificado son idénticos en las 4 operaciones; solo los
  hijos con los valores de negocio cambian — de ahí el 85.5% de overhead
  medido arriba, casi todo boilerplate repetido en cada mensaje.
- **¿Por qué un `SOAP Fault` es parte del contrato y no solo un error
  HTTP?** Porque el `faultcode`/`detail` son datos estructurados que el
  cliente puede parsear programáticamente (como hace `soap_client.py`
  para elegir un mensaje amigable por código), no solo un número de
  estado — el propio bug de la sección 2 de `EVIDENCIA_DESPLIEGUE_REAL.md`
  se detectó justamente porque el Fault devolvía un código y mensaje
  claros (`ValidacionFallida`, "El campo 'nombre' es obligatorio"), no un
  500 genérico.
