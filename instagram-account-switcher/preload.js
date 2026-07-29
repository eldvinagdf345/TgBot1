const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("accountsAPI", {
  list: () => ipcRenderer.invoke("accounts:list"),
  add: () => ipcRenderer.invoke("accounts:add"),
  switchTo: (id) => ipcRenderer.invoke("accounts:switch", id),
  rename: (id, label) => ipcRenderer.invoke("accounts:rename", id, label),
  togglePin: (id) => ipcRenderer.invoke("accounts:togglePin", id),
  toggleMobile: (id) => ipcRenderer.invoke("accounts:toggleMobile", id),
  remove: (id) => ipcRenderer.invoke("accounts:remove", id),
  openPool: () => ipcRenderer.invoke("pool:openWindow"),
  onActiveChanged: (cb) => ipcRenderer.on("accounts:activeChanged", (_e, id) => cb(id)),
});
