# Capturas de pantalla — GUI de escritorio

**Estado: completadas (2026-09-04).** Las 8 capturas descritas abajo ya
se tomaron de verdad (túnel SSH a `maquina-02`, servicio real, datos
reales) y están en `portafolio/ejercicio03/evidencias/app/`, incrustadas
en la sección 9 del reporte. Este documento se conserva como referencia
de cómo se generaron.

Esto no se pudo generar desde esta sesión de trabajo porque Tkinter
necesita una interfaz gráfica real y esta sandbox no tiene una. Hazlas tú
en tu máquina, en este orden. Cada una lleva: qué hacer antes de tomarla,
y qué debe verse en la imagen para que sirva como evidencia real (no una
captura ambigua que no demuestre nada).

## 0. Antes de empezar

1. Ten PostgreSQL corriendo con el esquema aplicado: `integracion02/db/00`
   a `06` + `library_soap_service/sql/soap_module.sql`, en ese orden
   (local, o vuelve a prender `maquina-02` en GCP y usa esa IP).
2. Arranca el servicio: `cd library_soap_service && python app.py`
   (con `.env` configurado — ver `README.md` del servicio).
3. Si usas la instancia GCP en vez de local, en
   `portafolio/trabajo-en-casa/tarea1/codigo/soap_client.py` cambia
   `SOAP_ENDPOINT_URL` a `http://<IP_DE_LA_INSTANCIA>:5000/soap`, o
   defínelo como variable de entorno antes de abrir la GUI.
4. Arranca la GUI: `cd portafolio/trabajo-en-casa/tarea1/codigo && python gui.py`

Guarda cada imagen en
`portafolio/ejercicio03/evidencias/app/<nombre_del_archivo>` (crea esa
carpeta si no existe) — así el reporte web ya tiene dónde enlazarlas.

## Capturas a tomar

**01_gui_ventana_completa.png**
Ventana completa recién abierta, mostrando el título "Cloud Models
Classifier" y las DOS pestañas visibles en la parte superior
("Clasificación local" y "Clasificación SOAP"). Demuestra que el modo
nuevo se agregó sin romper el diseño existente.

**02_gui_modo_local_ejemplo.png**
Pestaña "Clasificación local" con un ejemplo ya clasificado (nombre,
apellido, una descripción de servicio Cloud, y el resultado mostrado
abajo con el modelo identificado). Demuestra que el modo original sigue
intacto.

**03_gui_modo_soap_conceptos_cargados.png**
Pestaña "Clasificación SOAP", después de pulsar "Cargar conceptos
pendientes". Debe verse el combobox/lista lleno con conceptos REALES del
catálogo (título del libro + nombre del concepto, no un placeholder
vacío) — es la prueba visual de que la GUI sí habla con el servicio real.

**04_gui_modo_soap_registro_exitoso.png**
Formulario completo (nombre, apellidos, correo, concepto elegido, modelo
Cloud seleccionado) justo después de pulsar "Registrar clasificación"
con éxito. Debe verse el mensaje/label de confirmación con datos reales
(no un campo vacío).

**05_gui_modo_soap_fault_duplicado.png**
Repite exactamente el mismo registro del paso anterior (mismo concepto,
mismo correo) sin cambiar nada. Debe aparecer el `messagebox` de error
con el mensaje amigable de duplicado — el que escribe
`mensaje_amigable_fault()` en `soap_client.py`, no el XML crudo. Esta es
la captura central de la Tarea 2 del trabajo en casa.

**06_gui_modo_soap_progreso.png**
Después de pulsar "Ver mi progreso" con el mismo correo usado arriba.
Debe verse el resultado real: total de conceptos, cuántos clasificados,
cuántos pendientes, porcentaje.

**07_gui_modo_soap_fault_conexion.png** (opcional pero recomendado)
Detén el servicio Flask (`Ctrl+C` en su terminal) y, sin cerrar la GUI,
intenta "Cargar conceptos pendientes" o "Registrar clasificación" otra
vez. Debe verse el mensaje de "no se pudo conectar al servicio SOAP",
distinto del mensaje de Fault — demuestra que la GUI distingue error de
red vs. error de negocio.

**08_terminal_servicio_corriendo.png** (opcional, refuerza evidencia)
Captura de la terminal donde corre `python app.py`, mostrando en el log
las peticiones reales que generaron las capturas 03–06 (líneas
`GET /wsdl`, `POST /soap` con código 200/409, etc.).

## Después de tomarlas

Avísame o edita tú mismo `portafolio/ejercicio03/index.html`, sección 9
("Aplicaciones de escritorio como clientes SOAP"): agrega un bloque
`<div class="essay-figures">` con `<figure><img src="evidencias/app/...">`
para cada captura, siguiendo el mismo patrón que ya usa
`portafolio/ejercicio02/index.html` en su sección 13 (Galería de
evidencias) — cópialo de ahí como referencia exacta de marcado.
