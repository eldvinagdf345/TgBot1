const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("accountsAPI", {
  list: () => ipcRenderer.invoke("accounts:list"),
  add: () => ipcRenderer.invoke("accounts:add"),
  switchTo: (id) => ipcRenderer.invoke("accounts:switch", id),
  rename: (id, label) => ipcRenderer.invoke("accounts:rename", id, label),
  remove: (id) => ipcRenderer.invoke("accounts:remove", id),
});
