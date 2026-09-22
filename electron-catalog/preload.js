const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("catalogApi", {
  loadXml: (endpoint) => ipcRenderer.invoke("catalog:load-xml", endpoint),
  loadImage: (imageUrl) => ipcRenderer.invoke("catalog:load-image", imageUrl)
});
