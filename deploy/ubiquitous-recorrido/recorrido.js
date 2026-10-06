"use strict";
const stages = [
  {title:"Login y JWT",icon:"🔐",x:4,y:48,brief:"La aventura comienza: credenciales, sesión y tokens.",text:"Login (5000) verifica las credenciales. Emite un JWT de 20 minutos y un refresh token opaco; Redis guarda la sesión y el hash del refresh token. Nunca se guarda la contraseña en Redis.",q:"¿Qué recibe el cliente al iniciar sesión?",a:["Un JWT y un refresh token","La contraseña de Redis","Acceso directo a PostgreSQL"],correct:0},
  {title:"Libros / SOAP",icon:"📚",x:23,y:33,brief:"Consulta el catálogo y descubre la caché.",text:"Books (5001) ofrece lecturas públicas en XML o JSON. Redis guarda las respuestas durante 60 segundos; PostgreSQL conserva los datos definitivos. Crear o editar libros exige un rol admin o staff.",q:"Si Redis falla en una lectura pública…",a:["Se borran los libros","Se consulta PostgreSQL","Se cierra toda la app"],correct:1},
  {title:"Usuarios",icon:"👤",x:43,y:22,brief:"Cada cuenta tiene permisos y recursos propios.",text:"Users (5002) valida el JWT y su revocación en Redis. Cada usuario consulta y modifica su propia cuenta; el administrador puede listar usuarios. Un token válido no concede todos los permisos.",q:"¿Un JWT válido permite modificar cualquier usuario?",a:["Sí, siempre","Solo si hay caché","No; también se comprueban permisos"],correct:2},
  {title:"Autores",icon:"✒️",x:63,y:29,brief:"Autores públicos, cambios con autorización.",text:"Authors (5003) permite consultas públicas y las cachea durante 60 segundos. Las escrituras requieren admin o staff. Los cambios invalidan cachés de autores y de libros para actualizar la información relacionada.",q:"¿Quién puede escribir en autores?",a:["Cualquier visitante","Admin o staff","Solo Redis"],correct:1},
  {title:"Pedidos",icon:"📦",x:80,y:39,brief:"Un pedido, su propietario y el stock disponible.",text:"Pedidos (5004) exige JWT. El cliente crea y cancela sus propios pedidos, y el rol determina qué puede ver o cambiar. Las operaciones de pedidos invalidan cachés de libros porque el stock puede cambiar.",q:"¿Qué pedidos puede ver un customer?",a:["Los de todos","Los suyos","Ninguno"],correct:1},
  {title:"Pagos",icon:"💳",x:74,y:69,brief:"Candados e idempotencia evitan cobros duplicados.",text:"Pagos (5005) usa un candado de Redis por pedido y una clave de idempotencia por usuario. Repetir la misma operación permite recuperar su resultado. PostgreSQL refuerza la protección con una clave UNIQUE; si Redis falla, no se cobra.",q:"¿Para qué sirve la idempotencia?",a:["Para cobrar cada reintento","Para omitir el JWT","Para evitar ejecutar dos veces el mismo pago"],correct:2},
  {title:"Redis",icon:"⚡",x:53,y:65,brief:"Sesiones, revocación, caché y coordinación.",text:"Los seis servicios comparten Redis para sus funciones correspondientes: sesiones, refresh tokens, revocación, caché, candados e idempotencia. Si no se puede comprobar la revocación, las rutas protegidas responden 503. Las lecturas públicas siguen por PostgreSQL.",q:"Si Redis no puede comprobar la revocación…",a:["La ruta protegida responde 503","Se acepta cualquier JWT","Se desactiva la firma"],correct:0},
  {title:"PostgreSQL",icon:"🗄️",x:32,y:70,brief:"La fuente de verdad detrás de la biblioteca.",text:"PostgreSQL conserva los datos de Library. Cada microservicio accede con su propio rol y permisos EXECUTE de funciones. Los servicios no se llaman entre sí por HTTP: comparten PostgreSQL, Redis y el secreto JWT.",q:"¿Dónde están los datos definitivos?",a:["En la animación","Solo en la caché","En PostgreSQL"],correct:2},
  {title:"Renovar y salir",icon:"🏁",x:12,y:74,brief:"Rotación del refresh y revocación al terminar.",text:"Al renovar, el refresh token es de un solo uso y rota. La sesión tiene un límite de 24 horas. Al cerrar sesión se invalida el refresh y se revoca el JWT vigente en Redis hasta su vencimiento.",q:"¿Se puede reutilizar el refresh después de rotarlo?",a:["No, es de un solo uso","Sí, indefinidamente","Solo en pagos"],correct:0}
];
const $ = id => document.getElementById(id);
let current = -1, timer = null, overview = false;
const completed = new Set();
const flows = [
 ["Cliente","Login verifica","JWT + sesión en Redis"],
 ["Consulta pública","Caché Redis / PostgreSQL","XML o JSON"],
 ["JWT + revocación","Permisos de usuario","Perfil propio"],
 ["Lectura pública","Caché de autores","Catálogo actualizado"],
 ["JWT + propietario","Operación en PostgreSQL","Invalidar caché de stock"],
 ["JWT + permisos","Candado + idempotencia","Pago en PostgreSQL"],
 ["Servicio","Redis compartido","Caché o control de seguridad"],
 ["Rol de cada servicio","Funciones autorizadas","Datos definitivos"],
 ["Refresh de un solo uso","Rotar o cerrar sesión","Revocar JWT vigente"]
];
// Only learning progress is stored. No session or application data is accessed.
try {const saved=JSON.parse(localStorage.getItem("library-adventure-v1")||"[]");if(Array.isArray(saved))saved.forEach(i=>{if(Number.isInteger(i)&&i>=0&&i<stages.length)completed.add(i)})}catch{}
function updateProgress(){
 $("xp").textContent=`⭐ XP: ${completed.size*100}`;$("score").textContent=`🏅 Retos: ${completed.size}/9`;
 $("progress").value=completed.size;$("progress-label").textContent=completed.size===9?"🏆 ¡Todas las estrellas conseguidas!":`${completed.size} de 9 estrellas conseguidas`;
 document.querySelectorAll(".station").forEach((el,i)=>el.classList.toggle("done",completed.has(i)));
 try{localStorage.setItem("library-adventure-v1",JSON.stringify([...completed]))}catch{}
}
function celebrate(){
 const pieces=[];for(let n=0;n<22;n++){const piece=document.createElement("span");piece.className="confetti";piece.textContent=n%3===0?"⭐":"✦";piece.style.left=(Math.random()*100)+"%";piece.style.color=["#7652b9","#e3ad42","#38a385"][n%3];piece.style.animationDelay=(Math.random()*.4)+"s";$("celebration").append(piece);pieces.push(piece)}setTimeout(()=>pieces.forEach(p=>p.remove()),3000);
}
stages.forEach((s,i)=>{
 const button=document.createElement("button");button.className="station";button.style.left=s.x+"%";button.style.top=s.y+"%";button.setAttribute("aria-label",`${i+1}. ${s.title}`);
 button.innerHTML=`<span class="platform"><span class="icon">${s.icon}</span></span><span class="card"><span class="number">${i+1}</span><strong>${s.title}</strong><span class="station-port">${i<6 ? "Puerto " + (5000+i) : i===6 ? "Redis · 6379" : i===7 ? "PostgreSQL · 5432" : "Login · 5000"}</span><small>${s.brief}</small></span>`;
 button.onclick=()=>{stop();select(i,true)};$("stations").append(button);
});
function select(i,open=false){
 current=(i+stages.length)%stages.length;const s=stages[current];
 document.querySelectorAll(".station").forEach((el,n)=>{el.classList.toggle("active",n===current);el.setAttribute("aria-current",n===current?"step":"false")});
 $("traveler").style.left=(s.x+6)+"%";$("traveler").style.top=(s.y-5)+"%";
 $("guide").textContent=`${current+1}/9 · ${s.title}: ${s.brief}`;
 $("story-icon").textContent=s.icon;$("story-step").textContent=`ESTACIÓN ${String(current+1).padStart(2,"0")} / 09`;
 $("story-title").textContent=s.title;$("story-text").textContent=s.text;
 $("flow").replaceChildren();flows[current].forEach((label,n)=>{if(n){const arrow=document.createElement("b");arrow.textContent="→";$("flow").append(arrow)}const chip=document.createElement("span");chip.textContent=label;$("flow").append(chip)});
 if(open){overview=false;["question","answers","feedback"].forEach(id=>$(id).hidden=false);$("detail-icon").textContent=s.icon;$("detail-tag").textContent=`ESTACIÓN ${current+1} DE 9`;$("detail-title").textContent=s.title;$("explanation").textContent=s.text;$("question").textContent=s.q;$("feedback").textContent=completed.has(current)?"⭐ Ya superaste este reto. Puedes repasarlo.":"";$("answers").replaceChildren();
 s.a.forEach((label,n)=>{const b=document.createElement("button");b.className="answer";b.textContent=label;b.onclick=()=>{if(n===s.correct){const fresh=!completed.has(current);completed.add(current);b.classList.add("correct");$("feedback").textContent=fresh?"⭐ ¡Correcto! +100 XP. Has ganado esta estrella.":"✓ ¡Correcto! Esta estrella ya está en tu colección.";updateProgress();if(fresh)celebrate();if(completed.size===9)$("guide").textContent="🏆 ¡Misión completa! Conoces la arquitectura de Library."}else{b.classList.add("wrong");$("feedback").textContent="Inténtalo de nuevo. La explicación tiene la pista."}};$("answers").append(b)});
 $("next").textContent=current===8?"Terminar recorrido ✓":"Siguiente estación →";if(!$("detail").open)$("detail").showModal();startLesson(current);
 }
}
function stop(){clearInterval(timer);timer=null;$("play").textContent="▶ Recorrido automático";$("play").setAttribute("aria-pressed","false")}
$("play").onclick=()=>{if(timer){stop();return}$("detail").close();select(current<0||current===8?0:current);$("play").textContent="⏸ Pausar recorrido";$("play").setAttribute("aria-pressed","true");timer=setInterval(()=>{if(current===8){stop();return}select(current+1)},3500)};
$("reset").onclick=()=>{stop();completed.clear();$("detail").close();updateProgress();select(0)};
$("challenge").onclick=()=>{stop();select(current,true)};
$("previous").onclick=()=>{stop();select(current-1)};$("advance").onclick=()=>{stop();select(current+1)};
$("system-tour").onclick=()=>{stop();overview=true;$("detail-icon").textContent="🌐";$("detail-tag").textContent="ARQUITECTURA COMPARTIDA · 15 PASOS";$("detail-title").textContent="Microservicios, JWT y Redis: todo conectado";$("explanation").textContent="Sigue un inicio de sesión, una consulta protegida y el cierre de sesión para descubrir qué comparte cada servicio.";["question","answers","feedback"].forEach(id=>$(id).hidden=true);$("next").textContent="Volver al mapa";if(!$("detail").open)$("detail").showModal();startLesson(9)};
$("close").onclick=()=>$("detail").close();$("next").onclick=()=>{if(overview||current===8)$("detail").close();else select(current+1,true)};
document.addEventListener("keydown",e=>{if(e.key==="ArrowRight"||e.key==="ArrowLeft"){e.preventDefault();stop();select(current+(e.key==="ArrowRight"?1:-1),$("detail").open)}});
select(0);
updateProgress();


