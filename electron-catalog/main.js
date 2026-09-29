const { app, BrowserWindow, ipcMain, net, session } = require("electron");
const path = require("node:path");

function createWindow() {
  const window = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 980,
    minHeight: 650,
    title: "Catálogo de libros",
    backgroundColor: "#f7f8fc",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  window.loadFile("index.html");
}

function validarHttpUrl(value, mensaje) {
  let url;
  try {
    url = new URL(value);
    if (!/^https?:$/.test(url.protocol)) throw new Error();
  } catch {
    throw new Error(mensaje);
  }
  return url;
}

app.whenReady().then(() => {
  ipcMain.handle("catalog:load-xml", async (_event, endpoint) => {
    const url = validarHttpUrl(endpoint, "La URL debe usar HTTP o HTTPS.");
    const response = await net.fetch(url.toString(), {
      headers: { Accept: "application/xml, text/xml;q=0.9" }
    });
    if (!response.ok) {
      throw new Error(`El servidor respondió HTTP ${response.status}.`);
    }
    const contentType = response.headers.get("content-type") || "";
    const xml = await response.text();
    if (!contentType.includes("xml") && !xml.trimStart().startsWith("<")) {
      throw new Error("El endpoint no devolvió XML.");
    }
    return xml;
  });

  ipcMain.handle("catalog:load-image", async (_event, imageUrl) => {
    const url = validarHttpUrl(imageUrl, "La URL de imagen debe usar HTTP o HTTPS.");
    // Se descarga aquí (proceso principal) en vez de en el <img> del
    // renderer porque el servidor manda Cross-Origin-Resource-Policy:
    // same-origin -- Chromium bloquea esa carga cuando el origen de la
    // página es file://, aunque la URL responda 200 igual que el XML.
    const response = await net.fetch(url.toString());
    if (!response.ok) {
      throw new Error(`El servidor respondió HTTP ${response.status}.`);
    }
    const contentType = response.headers.get("content-type") || "image/jpeg";
    const buffer = Buffer.from(await response.arrayBuffer());
    return `data:${contentType};base64,${buffer.toString("base64")}`;
  });

  // Canal genérico JSON para /auth (login/registro/sesión) y las rutas
  // CRUD de /soap (books). net.fetch corre en el proceso principal, así
  // que no choca con Cross-Origin-Resource-Policy ni con contextIsolation
  // del renderer (mismo motivo que catalog:load-xml/-image de arriba).
  // La cookie de sesión de /auth/login se guarda en la sesión persistente
  // de Electron (session.defaultSession) y net.fetch la reenvía sola en
  // las siguientes peticiones al mismo origen -- por eso no se maneja
  // "a mano" en el renderer.
  ipcMain.handle("api:request", async (_event, { method, url: rawUrl, body, headers }) => {
    const url = validarHttpUrl(rawUrl, "La URL debe usar HTTP o HTTPS.");
    const init = { method: method || "GET", headers: { Accept: "application/json", ...(headers || {}) } };
    if (body !== undefined && body !== null) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await net.fetch(url.toString(), init);
    } catch (error) {
      return { ok: false, status: 0, error: "No se pudo conectar con el servidor." };
    }
    const text = await response.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { message: text };
    }
    return { ok: response.ok, status: response.status, data };
  });

  // Semáforo: solo interesa si el servicio responde, no su contenido --
  // por eso es un canal aparte y más simple que api:request (sin parsear
  // JSON ni fallar por CORS/Content-Type).
  ipcMain.handle("api:ping", async (_event, rawUrl) => {
    try {
      const url = validarHttpUrl(rawUrl, "URL inválida");
      const response = await net.fetch(url.toString(), { method: "GET" });
      return { up: response.ok, status: response.status };
    } catch {
      return { up: false, status: 0 };
    }
  });

  ipcMain.handle("api:clear-session", async () => {
    await session.defaultSession.clearStorageData({ storages: ["cookies"] });
  });

  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
