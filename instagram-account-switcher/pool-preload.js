const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("poolAPI", {
  list: () => ipcRenderer.invoke("pool:list"),
  add: (url, targetNumber) => ipcRenderer.invoke("pool:add", url, targetNumber),
  addBulk: (items) => ipcRenderer.invoke("pool:addBulk", items),
  update: (id, patch) => ipcRenderer.invoke("pool:update", id, patch),
  remove: (id) => ipcRenderer.invoke("pool:remove", id),
  open: (id) => ipcRenderer.invoke("pool:open", id),
});
