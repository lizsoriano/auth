"use strict";
// Educational messages, independent of the API and real user credentials.
const lessonScenes = [
 {service:"Login",port:"5000",steps:[
 ["client","proxy","1. Envías tus credenciales","POST /auth/login","El cliente envía correo y contraseña por HTTPS al proxy Nginx. Todavía no hay JWT."],
 ["proxy","service","2. La petición llega a Login","Nginx → Login :5000","Nginx elimina /auth/ y entrega POST /login al servicio de autenticación."],
 ["service","db","3. Verifica la cuenta","Login ↔ PostgreSQL","Login consulta la cuenta y comprueba el hash de la contraseña. Credenciales incorrectas terminan en 401."],
 ["service","redis","4. Crea la sesión","session:<sid> · refresh:<sha256>","Redis guarda la sesión y el hash del refresh token. El servicio firma localmente un JWT; Redis no firma el token."],
 ["service","client","5. Ya puedes entrar","JWT: 20 min · refresh opaco","La respuesta vuelve por Nginx al cliente con sus tokens. El JWT permite solicitar recursos protegidos según el rol."]]},
 {service:"Books / SOAP",port:"5001",steps:[
 ["client","proxy","1. Abres el catálogo","GET /soap/books","La lectura de libros es pública. Este ejemplo usa la API REST de Books; también existe su interfaz SOAP."],
 ["proxy","service","2. Books recibe la consulta","Nginx → Books :5001","El proxy elimina /soap/ y el servicio recibe GET /books. Puede representar la respuesta como XML o JSON."],
 ["service","redis","3. Busca en la caché","books:list:all · TTL 60 s","Books consulta Redis. Si hay un resultado vigente lo devuelve; aquí seguimos el caso en el que la caché no tiene el catálogo."],
 ["service","db","4. Recupera los datos","Fallo de caché → PostgreSQL","PostgreSQL devuelve los libros. Si Redis no está disponible, esta lectura pública también puede continuar por PostgreSQL."],
 ["service","redis","5. Conserva una copia temporal","Caché normalizada · 60 s","Books intenta guardar el resultado en Redis. Los datos definitivos permanecen en PostgreSQL."],
 ["service","client","6. Muestra los libros","Respuesta XML / JSON","El catálogo llega al cliente por el proxy. Las siguientes consultas pueden aprovechar la caché."]]},
 {service:"Users",port:"5002",steps:[
 ["client","proxy","1. Solicitas tu perfil","GET /users/users/me · Bearer JWT","El cliente presenta su JWT. El primer /users/ es el prefijo del proxy; /users/me es la ruta del servicio."],
 ["proxy","service","2. Valida el token","Nginx → Users :5002","Users comprueba localmente firma, algoritmo, emisor, vencimiento y claims. No llama al servicio Login para validar cada petición."],
 ["service","redis","3. Comprueba la revocación","jwt:revoked:<jti>","Users consulta Redis para saber si el JWT fue revocado. Si Redis no responde, el acceso protegido termina en 503."],
 ["service","db","4. Consulta tu cuenta","JWT válido + permisos","Con los permisos comprobados, Users obtiene el perfil propio desde PostgreSQL. Un JWT válido no autoriza modificar cuentas ajenas."],
 ["service","client","5. Devuelve tu perfil","Respuesta autenticada · no-store","La respuesta vuelve al cliente. Los datos autenticados no se guardan en la caché pública del catálogo."]]},
 {service:"Authors",port:"5003",steps:[
 ["client","proxy","1. Exploras autores","GET /authors/authors","La consulta pública llega a Nginx. El proxy conserva la ruta /authors después de quitar el prefijo."],
 ["proxy","service","2. Recibe Authors","Nginx → Authors :5003","Authors atiende la consulta sin exigir JWT para esta lectura pública."],
 ["service","redis","3. Busca los autores en caché","authors:list:<limit> · 60 s","Primero consulta la copia temporal de Redis. En este recorrido todavía no existe una copia vigente."],
 ["service","db","4. Consulta la fuente de verdad","Authors ↔ PostgreSQL","Obtiene los autores de PostgreSQL. Una lectura pública puede seguir funcionando si Redis falla."],
 ["service","redis","5. Actualiza la caché","Copia temporal de autores","Guarda el resultado durante 60 segundos. Las escrituras requieren admin o staff e invalidan las cachés relacionadas."],
 ["service","client","6. Presenta los autores","Respuesta pública","El cliente recibe los autores. No hubo una llamada HTTP entre Authors y Books."]]},
 {service:"Pedidos",port:"5004",steps:[
 ["client","proxy","1. Creas un pedido","POST /pedidos/pedidos · JWT","El cliente envía el pedido y su JWT al proxy. Esta operación modifica datos reales solo en la app; aquí se muestra una simulación."],
 ["proxy","service","2. Revisa identidad y rol","Nginx → Pedidos :5004","Pedidos valida localmente el JWT y comprueba los permisos de la operación."],
 ["service","redis","3. Descarta tokens revocados","jwt:revoked:<jti>","Consulta Redis antes de aceptar la operación protegida. Una caída de Redis impide continuar con la autenticación."],
 ["service","db","4. Registra el pedido","Pedidos ↔ PostgreSQL","El servicio ejecuta las funciones autorizadas de la base para registrar el pedido y sus cambios de stock."],
 ["service","redis","5. Invalida la caché de libros","Eliminar books:* relacionados","Como el stock puede haber cambiado, se invalidan las respuestas cacheadas de libros."],
 ["service","client","6. Confirma el resultado","Pedido creado","La respuesta llega al cliente. Pedidos usa la base compartida; no necesita invocar Books por HTTP."]]},
 {service:"Pagos",port:"5005",steps:[
 ["client","proxy","1. Envías un pago","POST /pagos/pagos · JWT · Idempotency-Key","La petición lleva una clave de idempotencia para reconocer reintentos de la misma operación."],
 ["proxy","service","2. Valida identidad","Nginx → Pagos :5005","Pagos valida el JWT. Un cliente solo puede pagar pedidos propios; los permisos y el propietario también se comprueban."],
 ["service","redis","3. Revisa revocación y coordina","Revocación · lock:order:<id> · payment:idem:…","Redis permite comprobar la revocación y coordinar el candado y la idempotencia. Si Redis falla, la operación responde 503 y no cobra."],
 ["service","db","4. Registra un único pago","PostgreSQL · idempotency_key UNIQUE","La base verifica y registra la operación. Su restricción UNIQUE añade protección frente a pagos duplicados."],
 ["service","redis","5. Guarda el resultado","Resultado idempotente · 24 h","Redis conserva el resultado para responder a un reintento equivalente. La reutilización de la clave con otro cuerpo produce 409."],
 ["service","client","6. Responde sin duplicar","Reintento → resultado anterior","El cliente recibe el resultado. Una misma operación no debe ejecutarse dos veces por volver a enviar la petición."]]},
 {service:"Servicio protegido",port:"5000–5005",steps:[
 ["client","proxy","1. Solicitas un recurso privado","Authorization: Bearer JWT","Veamos una comprobación de seguridad que comparten los servicios con rutas protegidas."],
 ["proxy","service","2. Valida el JWT localmente","Firma + claims + permisos","El servicio comprueba el token con el secreto compartido; no consulta a Login por HTTP."],
 ["service","redis","3. Consulta Redis","Redis :6379 · jwt:revoked:<jti>","Redis almacena revocación, sesiones, caché y coordinación según la operación. No reemplaza a PostgreSQL."],
 ["redis","service","4. Redis no responde","Ejemplo de fallo · no hay autorización","En este escenario Redis está caído. No es posible comprobar la revocación y el servicio bloquea el acceso protegido."],
 ["service","client","5. Responde 503","Servicio temporalmente no disponible","El cliente puede reintentar después. Las lecturas públicas de Books y Authors tienen otra política: pueden consultar PostgreSQL."]]},
 {service:"Microservicio",port:"5000–5005",steps:[
 ["client","proxy","1. Solicitas información","Cliente → Nginx","La base de datos no se expone directamente al cliente; la petición entra por la aplicación."],
 ["proxy","service","2. El servicio atiende la petición","Un servicio y su rol propio","Los seis servicios tienen roles separados de PostgreSQL y permisos para ejecutar sus funciones autorizadas."],
 ["service","db","3. Ejecuta una función autorizada","PostgreSQL :5432","PostgreSQL conserva la fuente de verdad de usuarios, catálogo, pedidos y pagos. Redis mantiene información auxiliar o temporal."],
 ["db","service","4. Entrega el resultado","Datos definitivos → servicio","El servicio transforma el resultado de la función al formato de su API. Los servicios comparten la base sin llamarse entre sí por HTTP."],
 ["service","client","5. Responde al cliente","Respuesta de la API","El cliente recibe la respuesta a través de Nginx, no credenciales ni acceso directo a la base."]]},
 {service:"Login",port:"5000",steps:[
 ["client","proxy","1. Solicitas renovar","POST /auth/token/refresh","El cliente envía el refresh token opaco para conseguir un JWT nuevo. Este token no es el JWT de acceso."],
 ["proxy","service","2. Recibe Login","Nginx → Login :5000","El proxy entrega POST /token/refresh. La renovación se atiende en el mismo servicio de autenticación."],
 ["service","redis","3. Comprueba sesión y refresh","Hash del refresh + sesión vigente","Login consulta la sesión y el refresh almacenado por hash. El refresh es de un solo uso y la sesión tiene un límite de 24 horas."],
 ["service","db","4. Revisa la cuenta actual","Usuario activo y rol actual","Login comprueba el estado actual de la cuenta antes de renovar. Una cuenta deshabilitada no puede continuar la sesión."],
 ["service","redis","5. Rota y revoca","Consumir refresh · revocar JWT anterior","Se consume el refresh anterior, se almacena el nuevo y se revoca el JWT previo si sigue vigente."],
 ["service","client","6. Devuelve tokens nuevos","Nuevo JWT + nuevo refresh","La respuesta vuelve al cliente. Para salir, POST /auth/logout invalida la sesión y el refresh y revoca el JWT vigente."]]},
];
lessonScenes.push({service:"Login",port:"5000",steps:[
 ["client","proxy","1. Un punto de entrada","HTTPS → Nginx","El cliente entra por Nginx. Los puertos 5000 a 5005 son internos; Redis y PostgreSQL tampoco se exponen al navegador."],
 ["proxy","service","2. Login autentica","/auth/login → :5000/login","Nginx selecciona Login. Los otros cinco servicios son Books :5001, Users :5002, Authors :5003, Pedidos :5004 y Pagos :5005."],
 ["service","db","3. Verifica la cuenta","PostgreSQL · rol propio por servicio","Cada servicio usa un rol distinto para ejecutar sus funciones autorizadas. PostgreSQL es la fuente de verdad común."],
 ["service","redis","4. Crea estado compartido","session:<sid> · refresh:<sha256>","Redis conserva sesión y hash del refresh. Sesión: 30 minutos deslizantes y máximo absoluto de 24 horas; refresh: hasta 24 horas."],
 ["service","client","5. Entrega el JWT","HS256 · exp: 20 min · jti único","Login firma el JWT. Sus claims contienen identificador, rol, emisor y tiempos; no contraseñas. Un JWT firmado no cifra su contenido."],
 ["client","proxy","6. Presenta el mismo token","Authorization: Bearer <JWT>","El cliente puede presentar el JWT a cualquiera de los seis servicios. Que compartan validación no significa que todos concedan los mismos permisos."],
 ["proxy","service","7. Users valida localmente","Users :5002 · módulo común","Users usa el mismo módulo de validación, emisor y secreto HS256 configurado en los servicios. No llama a Login por HTTP. El secreto nunca viaja al cliente.","Users","5002"],
 ["service","redis","8. Consulta la revocación común","jwt:revoked:<jti>","Users comprueba la misma lista compartida que Books, Authors, Pedidos y Pagos usan en sus rutas protegidas. Sin Redis, estas rutas responden 503.","Users","5002"],
 ["service","db","9. Aplica permisos y consulta","Rol + propietario → perfil","La firma no basta: Users comprueba a quién pertenece el recurso. Los perfiles privados se consultan en PostgreSQL y no se mezclan con la caché pública.","Users","5002"],
 ["service","client","10. Devuelve el recurso","Cache-Control: no-store","La respuesta del perfil vuelve por Nginx. Las lecturas públicas de libros y autores pueden usar caché de 60 segundos; si falta, recurren a PostgreSQL.","Users","5002"],
 ["client","proxy","11. El cliente cierra sesión","POST /auth/logout · cookie de sesión","Logout usa la sesión de Login identificada por su cookie. No debe confundirse con una operación basada únicamente en Bearer JWT."],
 ["proxy","service","12. Login procesa la salida","Login :5000 · sesión actual","Nginx dirige el cierre al servicio Login, que conoce la sesión y el JWT vigente."],
 ["service","redis","13. Revoca para todos","Eliminar sesión y refresh · revocar jti","Login invalida la sesión y el refresh y guarda la marca de revocación hasta el vencimiento del JWT. Todos los servicios consultan este mismo Redis."],
 ["redis","service","14. Otro servicio rechaza ese JWT","Pagos :5005 → token revocado","Si después se intenta usar el token revocado en Pagos, su validación consulta Redis y detecta la marca. El módulo común rechaza el token con 401 antes de registrar un pago.","Pagos","5005"],
 ["service","client","15. Seguridad compartida","401 · iniciar sesión de nuevo","El rechazo vuelve por el proxy. Los servicios comparten estado y validación, pero conservan sus rutas, permisos y roles PostgreSQL independientes.","Pagos","5005"]
]});
const diagramNodes={client:{x:75,y:150,label:"Cliente",icon:"📱"},proxy:{x:225,y:150,label:"Nginx",icon:"🚪"},service:{x:395,y:150,label:"Servicio",icon:"⚙️"},db:{x:580,y:65,label:"PostgreSQL",icon:"🗄️"},redis:{x:580,y:235,label:"Redis",icon:"⚡"}};
let lessonTimer=null,lessonIndex=0,lessonStep=0,lessonPlaying=false;
const animEl=id=>document.getElementById(id);
function pausePackets(paused){const svg=animEl("lesson-diagram").querySelector("svg");if(svg){if(paused)svg.pauseAnimations();else svg.unpauseAnimations()}animEl("lesson-diagram").classList.toggle("paused",paused)}
function stopLesson(){pausePackets(true);clearInterval(lessonTimer);lessonTimer=null;lessonPlaying=false;animEl("lesson-play").textContent="▶ Reproducir";animEl("lesson-play").setAttribute("aria-pressed","false")}
function playLesson(){stopLesson();lessonPlaying=true;if(!window.matchMedia("(prefers-reduced-motion: reduce)").matches)pausePackets(false);animEl("lesson-play").textContent="⏸ Pausar";animEl("lesson-play").setAttribute("aria-pressed","true");lessonTimer=setInterval(()=>{if(lessonStep===lessonScenes[lessonIndex].steps.length-1){stopLesson();return}lessonStep++;renderLesson()},6500)}
function renderLesson(){
 const scene=lessonScenes[lessonIndex],step=scene.steps[lessonStep],from=diagramNodes[step[0]],to=diagramNodes[step[1]];
 animEl("lesson-route").textContent=step[3];animEl("lesson-heading").textContent=step[2];animEl("lesson-copy").textContent=step[4];animEl("lesson-count").textContent=`Paso ${lessonStep+1} de ${scene.steps.length}`;
 animEl("lesson-diagram").innerHTML=`<svg viewBox="0 0 680 300" aria-hidden="true"><path class="diagram-wire" d="M75 150H395 M395 150L580 65 M395 150L580 235"/><path class="diagram-active-wire" d="M${from.x} ${from.y} L${to.x} ${to.y}"/><circle class="diagram-packet" r="8" fill="#8055cf"><animateMotion dur="2s" repeatCount="indefinite" path="M${from.x} ${from.y} L${to.x} ${to.y}"/></circle></svg>`;
 Object.entries(diagramNodes).forEach(([key,node])=>{const box=document.createElement("div");box.className="diagram-node"+(key===step[0]?" sending":"")+(key===step[1]?" receiving":"");box.style.left=(node.x/680*100)+"%";box.style.top=(node.y/300*100)+"%";const icon=document.createElement("span");icon.textContent=node.icon;const title=document.createElement("strong");title.textContent=key==="service"?(step[5]||scene.service):node.label;const port=document.createElement("small");port.textContent=key==="service"?":"+(step[6]||scene.port):key==="db"?":5432":key==="redis"?":6379":key==="proxy"?"Proxy HTTPS":"Application";box.append(icon,title,port);animEl("lesson-diagram").append(box)});
 animEl("lesson-dots").replaceChildren();scene.steps.forEach((_,n)=>{const dot=document.createElement("button");dot.className="lesson-dot"+(n===lessonStep?" selected":"");dot.setAttribute("aria-label",`Ver paso ${n+1}`);dot.setAttribute("aria-pressed",String(n===lessonStep));dot.onclick=()=>{stopLesson();lessonStep=n;renderLesson()};animEl("lesson-dots").append(dot)});
 pausePackets(!lessonPlaying || window.matchMedia("(prefers-reduced-motion: reduce)").matches);animEl("lesson-back").disabled=lessonStep===0;animEl("lesson-forward").disabled=lessonStep===scene.steps.length-1;
}
function startLesson(index){stopLesson();lessonIndex=index;lessonStep=0;renderLesson();if(!window.matchMedia("(prefers-reduced-motion: reduce)").matches)playLesson()}
animEl("lesson-play").onclick=()=>{if(lessonPlaying)stopLesson();else{if(lessonStep===lessonScenes[lessonIndex].steps.length-1){lessonStep=0;renderLesson()}playLesson()}};
animEl("lesson-back").onclick=()=>{stopLesson();lessonStep=Math.max(0,lessonStep-1);renderLesson()};animEl("lesson-forward").onclick=()=>{stopLesson();lessonStep=Math.min(lessonScenes[lessonIndex].steps.length-1,lessonStep+1);renderLesson()};
document.getElementById("detail").addEventListener("close",stopLesson);
document.addEventListener("visibilitychange",()=>{if(document.hidden)stopLesson()});

