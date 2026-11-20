/* Monterrey GPS Tracker — mapa con Leaflet + OpenStreetMap (diseño tipo Google Maps).
 *
 * Qué dibuja:
 *   · Las RUTAS REALES por las calles (GeoJSON de /geojson/routes, calculadas con OSRM sobre OpenStreetMap).
 *   · Cada vehículo como un marcador con flecha de rumbo y su estela; los datos llegan por WebSocket (role=map)
 *     en formato GeoJSON (Point) junto con la calle actual y la velocidad promedio.
 *   · Toque en un vehículo: su calle, velocidad, velocidad PROMEDIO (Σd / Σt) y su recorrido en GeoJSON.
 *   · Toque en cualquier punto del mapa: identifica la calle con Nominatim (OpenStreetMap).
 */
"use strict";

const MONTERREY = [25.6866, -100.3161];
const MAX_TRAIL = 100;
const STALE_MS = 15000;
const ROUTE_COLORS = ["#1a73e8", "#d93025", "#188038", "#f9ab00", "#9334e6", "#12b5cb"];
const COMPASS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];

const map = L.map("map", { fadeAnimation: false, zoomControl: false }).setView(MONTERREY, 12);
L.control.zoom({ position: "bottomright" }).addTo(map);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);
L.control.scale({ imperial: false, position: "bottomright" }).addTo(map);

const layers = {
  routes: L.layerGroup().addTo(map), trails: L.layerGroup().addTo(map),
  signals: L.layerGroup().addTo(map), crossings: L.layerGroup().addTo(map),
  calming: L.layerGroup().addTo(map), schools: L.layerGroup().addTo(map)
};
/* Señales viales (de /geojson/signals): semáforos, cruces, altos, topes y escuelas son de OpenStreetMap; los baches son simulados. */
const KINDS = {
  traffic_signals: { label: "Semáforo", icon: "🚦", color: "#d93025", layer: "signals" },
  crossing: { label: "Cruce peatonal", icon: "🚸", color: "#1a73e8", layer: "crossings" },
  stop: { label: "Alto", icon: "🛑", color: "#b31412", layer: "calming" },
  bump: { label: "Tope", icon: "⚠️", color: "#e37400", layer: "calming" },
  pothole: { label: "Bache", icon: "🕳️", color: "#5f6368", layer: "calming" },
  school: { label: "Zona escolar", icon: "🏫", color: "#188038", layer: "schools" }
};
const EVENT_ICONS = { ...Object.fromEntries(Object.entries(KINDS).map(([k, v]) => [k, v.icon])), rush: "🚗", night: "🌙", clear: "✅" };
const DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
let schedule = null;                       // horarios (vienen en el GeoJSON de señales)
const simClock = { tod: null, day: null }; // hora simulada que reporta el simulador
const signalMarkers = [];                  // { marker, props } de cada semáforo, para cambiarlo de color
const vehicles = new Map(); // vehicle_id -> { marker, line, data, lastSeen }
const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const listEl = $("list");
const emptyEl = $("empty");
let firstFit = true;
let routesBounds = null;
let filterText = "";

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n, digits = 0) => (Number.isFinite(Number(n)) ? Number(n).toFixed(digits) : "–");
const compass = (deg) => COMPASS[Math.round((((Number(deg) || 0) % 360) + 360) % 360 / 45) % 8];
const isWide = () => window.innerWidth > 760;

function colorFor(id) {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return `hsl(${(h * 137.508) % 360} 65% 42%)`; // ángulo áureo: ids consecutivos dan tonos bien separados
}
const initials = (id) => id.replace(/[^A-Za-z0-9]/g, "").slice(-3).toUpperCase();

/* GeoJSON Point [lon, lat] -> el objeto plano que usa el resto del código. */
function fromFeature(feature) {
  const [longitude, latitude] = feature.geometry.coordinates;
  return { ...feature.properties, vehicle_id: feature.properties.vehicle_id || feature.id, latitude, longitude };
}

function iconFor(v) {
  return L.divIcon({
    className: "", iconSize: [44, 44], iconAnchor: [22, 22],
    html: `<div class="pin${Number(v.speed) < 1 ? " stopped" : ""}" style="--c:${colorFor(v.vehicle_id)}"><span class="ring"></span>
           <div class="core"><div class="arrow" style="transform:rotate(${Number(v.heading) || 0}deg)"></div></div></div>`
  });
}

/* Tarjeta de información, como las de Google Maps. */
function popupHtml(v) {
  const km = Number.isFinite(Number(v.trip_distance_m)) ? num(v.trip_distance_m / 1000, 1) : "–";
  return `<div style="--c:${colorFor(v.vehicle_id)}">
    <div class="card-head"><span class="avatar">${esc(initials(v.vehicle_id))}</span>
      <div><h3>${esc(v.vehicle_id)}</h3><p>${esc(v.street || "Calle sin dato")}</p></div></div>
    <div class="card-body">
      ${v.event ? `<div class="event ev-${esc(v.event)}"><span>${EVENT_ICONS[v.event] || "ℹ️"}</span><span>${esc(v.event_text || "")}</span></div>` : ""}
      <div class="stats">
        <div class="stat"><b>${num(v.speed)}</b><span>km/h ahora</span></div>
        <div class="stat"><b>${v.avg_speed == null ? "–" : num(v.avg_speed, 1)}</b><span>km/h promedio</span></div>
        <div class="stat"><b>${km}</b><span>km recorridos</span></div>
      </div>
      <div class="actions">
        <button class="btn primary" type="button" data-act="track" data-id="${esc(v.vehicle_id)}">Ver recorrido</button>
        <button class="btn" type="button" data-act="geo" data-lat="${v.latitude}" data-lon="${v.longitude}">¿Qué calle es?</button>
      </div>
      <div class="result"></div>
      <div class="src">Rumbo ${num(v.heading)}° ${compass(v.heading)}</div>
    </div></div>`;
}

function upsert(v, trail) {
  const pos = [v.latitude, v.longitude];
  let e = vehicles.get(v.vehicle_id);
  if (!e) {
    e = {
      marker: L.marker(pos, { icon: iconFor(v) }).addTo(map)
        .bindTooltip(esc(v.vehicle_id), { permanent: true, direction: "right", offset: [18, 0], className: "vid" })
        .bindPopup(() => popupHtml(vehicles.get(v.vehicle_id).data), { maxWidth: 320, className: "gm-popup", autoPanPaddingTopLeft: [isWide() ? 400 : 20, 70] }),
      line: L.polyline(trail && trail.length ? trail : [pos], { color: colorFor(v.vehicle_id), weight: 4, opacity: 0.8 }).addTo(layers.trails),
      data: v, lastSeen: Date.now()
    };
    vehicles.set(v.vehicle_id, e);
  } else {
    e.marker.setLatLng(pos).setIcon(iconFor(v));
    e.line.addLatLng(pos);
    const pts = e.line.getLatLngs();
    if (pts.length > MAX_TRAIL) e.line.setLatLngs(pts.slice(-MAX_TRAIL));
    e.data = v; e.lastSeen = Date.now();
  }
  e.marker.setOpacity(1);
  if (v.sim_time) noteClock(v.sim_time, v.sim_day);
}

function remove(id) {
  const e = vehicles.get(id);
  if (!e) return;
  map.removeLayer(e.marker); layers.trails.removeLayer(e.line);
  vehicles.delete(id);
}

/* Indicadores de la flota: velocidad promedio = Σ distancia / Σ tiempo (NO el promedio de las velocidades). */
function renderKpis() {
  let distance = 0, time = 0;
  for (const { data } of vehicles.values()) {
    if (Number.isFinite(Number(data.trip_distance_m)) && Number(data.trip_time_s) > 0) {
      distance += Number(data.trip_distance_m); time += Number(data.trip_time_s);
    }
  }
  $("kpiCount").textContent = vehicles.size;
  $("kpiAvg").textContent = time > 0 ? num((distance / time) * 3.6, 1) : "–";
}

/* La lista lateral se redibuja como máximo 2 veces por segundo, aunque lleguen muchos vehículos por segundo. */
let listTimer = null;
function scheduleList() {
  if (listTimer) return;
  listTimer = setTimeout(() => { listTimer = null; renderList(); }, 500);
}

function matches(id, data) {
  return !filterText || id.toLowerCase().includes(filterText) || String(data.street || "").toLowerCase().includes(filterText);
}

function renderList() {
  const ids = [...vehicles.keys()].sort();
  $("count").textContent = ids.length;
  emptyEl.hidden = ids.length > 0;
  renderKpis();
  listEl.replaceChildren(...ids.filter((id) => matches(id, vehicles.get(id).data)).map((id) => {
    const { data, lastSeen } = vehicles.get(id);
    const li = document.createElement("li");
    li.className = Date.now() - lastSeen > STALE_MS ? "stale" : "";
    li.style.setProperty("--c", colorFor(id));
    li.innerHTML = `<span class="avatar">${esc(initials(id))}</span>
      <div><div class="name">${esc(id)}</div>
      <div class="street" title="${esc(data.street || "")}">${esc(data.street || "Calle sin dato")}</div>
      <div class="ev-line" title="${esc(data.event_text || "")}">${data.event ? (EVENT_ICONS[data.event] || "") + " " + esc(data.event_text || "") : compass(data.heading) + " · " + num(data.latitude, 4) + ", " + num(data.longitude, 4)}</div></div>
      <span class="speed">${num(data.speed)} km/h<small>prom. ${data.avg_speed == null ? "–" : num(data.avg_speed, 1)}</small></span>`;
    li.addEventListener("click", () => {
      map.flyTo([data.latitude, data.longitude], 15, { duration: 0.8 });
      vehicles.get(id).marker.openPopup();
    });
    return li;
  }));
}

function onMessage(msg) {
  if (msg.type === "snapshot") {
    const incoming = new Set(msg.vehicles.map((v) => v.vehicle_id));
    for (const id of [...vehicles.keys()]) if (!incoming.has(id)) remove(id);
    for (const v of msg.vehicles) { remove(v.vehicle_id); upsert(v, v.trail); }
    if (firstFit && msg.vehicles.length && !routesBounds) fitAll();
  } else if (msg.type === "update") {
    upsert(msg.feature ? fromFeature(msg.feature) : msg.vehicle);
  } else if (msg.type === "updates") {   // un lote de vehículos en un solo mensaje (GeoJSON FeatureCollection)
    const list = msg.features ? msg.features.features.map(fromFeature) : msg.vehicles;
    for (const v of list) upsert(v);
  }
  scheduleList();
}

let retry = 1000;
function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws?role=map`);
  ws.onopen = () => { retry = 1000; statusEl.textContent = "En vivo"; statusEl.className = "on"; };
  ws.onmessage = (ev) => { try { onMessage(JSON.parse(ev.data)); } catch (err) { console.error(err); } };
  ws.onclose = () => {
    statusEl.textContent = "Reconectando…"; statusEl.className = "";
    setTimeout(connect, retry); retry = Math.min(retry * 2, 10000);
  };
  ws.onerror = () => ws.close();
}

/* Encuadra los vehículos (o las rutas) dejando libre la zona que tapa el panel flotante. */
function fitAll() {
  const points = [...vehicles.values()].map((e) => [e.data.latitude, e.data.longitude]);
  const bounds = points.length ? L.latLngBounds(points) : routesBounds;
  if (!bounds) return;
  map.invalidateSize();
  map.fitBounds(bounds, { paddingTopLeft: [isWide() ? 400 : 30, 80], paddingBottomRight: [40, isWide() ? 40 : 320], maxZoom: 14 });
  firstFit = false;
}

/* ------------------------------------------------------------ rutas (GeoJSON) */
async function loadRoutes() {
  try {
    const response = await fetch("/geojson/routes");
    if (!response.ok) return;
    const data = await response.json();
    // Cada ruta se dibuja dos veces, como las indicaciones de Google Maps: un borde blanco y encima el color.
    L.geoJSON(data, { style: () => ({ color: "#fff", weight: 9, opacity: 0.9, lineCap: "round", lineJoin: "round" }), interactive: false }).addTo(layers.routes);
    const colored = L.geoJSON(data, {
      style: (feature) => ({ color: ROUTE_COLORS[data.features.indexOf(feature) % ROUTE_COLORS.length], weight: 5, opacity: 0.85, lineCap: "round", lineJoin: "round" }),
      onEachFeature: (feature, line) => {
        const p = feature.properties;
        line.bindTooltip(`<b>${esc(p.name)}</b><br>${num(p.distance_m / 1000, 1)} km · ${num(p.duration_s / 60)} min · ${new Set(p.segments.map((s) => s.street)).size} calles`, { sticky: true });
        line.on("mouseover", () => line.setStyle({ weight: 8 }));
        line.on("mouseout", () => colored.resetStyle(line));
      }
    }).addTo(layers.routes);
    data.features.forEach((feature, index) => {
      const p = feature.properties;
      const li = document.createElement("li");
      li.style.setProperty("--c", ROUTE_COLORS[index % ROUTE_COLORS.length]);
      li.innerHTML = `<span class="swatch"></span><span>${esc(p.name)}</span>
        <span class="meta">${num(p.distance_m / 1000, 1)} km<br>${num(p.duration_s / 60)} min</span>`;
      li.style.cursor = "pointer";
      li.addEventListener("click", () => map.fitBounds(L.geoJSON(feature).getBounds(),
        { paddingTopLeft: [isWide() ? 400 : 30, 80], paddingBottomRight: [40, isWide() ? 40 : 320] }));
      $("routes").append(li);
      (p.waypoints || []).forEach((w) => {
        L.circleMarker([w.latitude, w.longitude], { radius: 5, color: "#5f6368", weight: 2, fillColor: "#fff", fillOpacity: 1 })
          .bindTooltip(esc(w.name)).addTo(layers.routes);
      });
    });
    routesBounds = colored.getBounds();
    if (firstFit) fitAll();
  } catch (err) { console.error("No se pudieron cargar las rutas", err); }
}

/* --------------------------------------- calle de un punto (Nominatim / OpenStreetMap) */
async function reverseGeocode(lat, lon, target) {
  target.innerHTML = "Buscando calle en OpenStreetMap…";
  try {
    const response = await fetch(`/geocode/reverse?lat=${lat}&lon=${lon}`);
    const body = await response.json();
    if (!response.ok) { target.innerHTML = `<span class="error">${esc(body.error || "No se pudo identificar la calle")}</span>`; return; }
    target.innerHTML = `<b>${esc(body.street || "Calle sin nombre")}</b><br>${esc([body.suburb, body.city, body.state].filter(Boolean).join(", "))}
      <div class="src">${esc(body.source)}${body.cached ? " · desde caché" : ""}</div>`;
  } catch (err) { target.innerHTML = '<span class="error">Sin conexión con el servicio</span>'; }
}

async function showTrack(id, target) {
  target.innerHTML = "Calculando recorrido…";
  try {
    const response = await fetch(`/vehicles/${encodeURIComponent(id)}/track.geojson`);
    const feature = await response.json();
    if (!response.ok) { target.innerHTML = `<span class="error">${esc(feature.error || "Sin datos")}</span>`; return; }
    const p = feature.properties;
    target.innerHTML = `Recorrido registrado: <b>${num(p.distance_m / 1000, 2)} km</b> en ${p.points} posiciones<br>
      Velocidad promedio: <b>${p.avg_speed_kmh == null ? "–" : num(p.avg_speed_kmh, 1) + " km/h"}</b>
      <div class="src">${esc(p.method)}</div>`;
  } catch (err) { target.innerHTML = '<span class="error">Sin conexión con el servicio</span>'; }
}

map.on("popupopen", (event) => {
  const root = event.popup.getElement();
  if (!root) return;
  root.querySelectorAll("button[data-act]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = root.querySelector(".result");
      if (button.dataset.act === "track") showTrack(button.dataset.id, target);
      else reverseGeocode(button.dataset.lat, button.dataset.lon, target);
    });
  });
});

map.on("click", (event) => {
  const popup = L.popup({ maxWidth: 300, className: "gm-popup" }).setLatLng(event.latlng)
    .setContent('<div class="click-card"><h3>📍 ¿Qué calle es esta?</h3><div class="result"></div></div>').openOn(map);
  reverseGeocode(event.latlng.lat.toFixed(6), event.latlng.lng.toFixed(6), popup.getElement().querySelector(".result"));
});

/* ------------------------------------------- señales viales y horarios (misma lógica que traffic.py) */
const toSeconds = (hhmm) => { const [h, m, sec] = hhmm.split(":").map(Number); return h * 3600 + m * 60 + (sec || 0); };
const inWindow = (tod, a, b) => { const s0 = toSeconds(a), e0 = toSeconds(b); return s0 <= e0 ? tod >= s0 && tod < e0 : tod >= s0 || tod < e0; };
const rushNow = (tod, day) => schedule.rush_hours.find((w) => w.days.includes(day) && inWindow(tod, w.start, w.end));
const schoolNow = (tod, day) => schedule.school.days.includes(day) && schedule.school.windows.some(([a, b]) => inWindow(tod, a, b));
const nightNow = (tod) => inWindow(tod, schedule.night.start, schedule.night.end);

function signalPhase(props, tod, night) {
  if (night) return "flash";
  const cycle = props.cycle_s || 80, green = props.green_s || 38;
  const phase = (tod + (props.offset_s || 0)) % cycle;
  return phase < green ? "green" : phase < green + 4 ? "yellow" : "red";
}

function markerIcon(kind, props) {
  const k = KINDS[kind];
  if (kind === "traffic_signals") return L.divIcon({ className: "", iconSize: [18, 18], html: '<div class="mk sig"></div>' });
  return L.divIcon({ className: "", iconSize: [24, 24], html: `<div class="mk mk-${kind}" style="--k:${k.color}">${k.icon}</div>` });
}

function hazardTip(p) {
  const k = KINDS[p.kind];
  let extra = p.name ? `<br>${esc(p.name)}` : "";
  if (p.kind === "traffic_signals") extra += `<br>Ciclo ${p.cycle_s} s · verde ${p.green_s} s`;
  if (p.kind === "pothole") extra += `<br>Severidad: ${esc(p.severity)}`;
  if (p.kind === "school") extra += `<br>Zona de ${p.zone_m} m · ${schedule.school.speed_limit_kmh} km/h en horario escolar`;
  return `<b>${k.icon} ${k.label}</b>${extra}<br><small>${p.source === "simulado" ? "Simulado" : "Fuente: OpenStreetMap"}</small>`;
}

async function loadSignals() {
  try {
    const response = await fetch("/geojson/signals");
    if (!response.ok) return;
    const data = await response.json();
    schedule = data.schedule;
    const seen = new Set();   // el mismo semáforo puede estar en varias rutas
    for (const feature of data.features) {
      const p = feature.properties, [lon, lat] = feature.geometry.coordinates;
      const key = `${p.kind}:${lon}:${lat}`;
      if (!KINDS[p.kind] || seen.has(key)) continue;
      seen.add(key);
      const marker = L.marker([lat, lon], { icon: markerIcon(p.kind, p), zIndexOffset: -500, keyboard: false })
        .bindTooltip(hazardTip(p), { direction: "top" }).addTo(layers[KINDS[p.kind].layer]);
      if (p.kind === "traffic_signals") signalMarkers.push({ marker, props: p });
    }
    renderSchedule();
    renderLegend();
    updateSignals();
  } catch (err) { console.error("No se pudieron cargar las señales viales", err); }
}

function updateSignals() {
  if (!schedule || simClock.tod == null) return;
  const night = nightNow(simClock.tod);
  for (const { marker, props } of signalMarkers) {
    const el = marker.getElement() && marker.getElement().firstChild;
    if (el) el.className = `mk sig ${signalPhase(props, simClock.tod, night)}`;
  }
}

let clockTimer = null;
function noteClock(text, day) {
  simClock.tod = toSeconds(text);
  if (day != null) simClock.day = day;
  if (clockTimer) return;
  clockTimer = setTimeout(() => { clockTimer = null; updateSignals(); renderSchedule(); }, 800);
}

function renderSchedule() {
  if (!schedule || simClock.tod == null) return;
  const { tod, day } = simClock;
  $("simTime").textContent = `${String(Math.floor(tod / 3600)).padStart(2, "0")}:${String(Math.floor(tod % 3600 / 60)).padStart(2, "0")}`;
  $("simDay").textContent = day == null ? "" : DAYS[day];
  const rush = rushNow(tod, day), school = schoolNow(tod, day), night = nightNow(tod);
  $("simStatus").textContent = [night ? "🌙 Noche · semáforos intermitentes" : "", rush ? `🚗 ${rush.name} · tráfico lento` : "",
    school ? `🏫 Horario escolar · ${schedule.school.speed_limit_kmh} km/h junto a escuelas` : ""].filter(Boolean).join(" · ") || "✅ Horario normal";
  const rows = schedule.rush_hours.map((w) => [w.name, `${w.start}–${w.end}`, rush === w])
    .concat([["Horario escolar", schedule.school.windows.map((w) => w.join("–")).join(", "), school],
             ["Noche", `${schedule.night.start}–${schedule.night.end}`, night]]);
  $("schedule").replaceChildren(...rows.map(([name, hours, active]) => {
    const li = document.createElement("li");
    li.className = active ? "active" : "";
    li.innerHTML = `<span>${esc(name)}</span><span>${esc(hours)}</span>`;
    return li;
  }));
}

function renderLegend() {
  $("legend").replaceChildren(...Object.entries(KINDS).map(([kind, k]) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="mk" style="--k:${k.color}">${k.icon}</span><span>${k.label}${kind === "pothole" ? " (simulado)" : ""}</span>`;
    return li;
  }));
}

map.on("zoomend", () => $("map").classList.toggle("low-zoom", map.getZoom() < 14));
$("map").classList.toggle("low-zoom", map.getZoom() < 14);

/* ------------------------------------------------------- panel: chips y buscador */
document.querySelectorAll(".chip[data-layer]").forEach((chip) => chip.addEventListener("click", () => {
  const layer = layers[chip.dataset.layer];
  chip.classList.toggle("on");
  if (chip.classList.contains("on")) layer.addTo(map); else map.removeLayer(layer);
}));
$("fit").addEventListener("click", fitAll);
$("q").addEventListener("input", (event) => { filterText = event.target.value.trim().toLowerCase(); renderList(); });

setInterval(() => {
  for (const e of vehicles.values()) {
    const stale = Date.now() - e.lastSeen > STALE_MS;
    e.marker.setOpacity(stale ? 0.4 : 1);
  }
  scheduleList();
}, 5000);

new ResizeObserver(() => map.invalidateSize()).observe($("map"));
loadRoutes();
loadSignals();
connect();
