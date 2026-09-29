const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("catalogApi", {
  loadXml: (endpoint) => ipcRenderer.invoke("catalog:load-xml", endpoint),
  loadImage: (imageUrl) => ipcRenderer.invoke("catalog:load-image", imageUrl),
  request: (method, url, body, headers) => ipcRenderer.invoke("api:request", { method, url, body, headers }),
  ping: (url) => ipcRenderer.invoke("api:ping", url),
  clearSession: () => ipcRenderer.invoke("api:clear-session")
});
