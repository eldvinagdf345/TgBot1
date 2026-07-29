const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("accountsAPI", {
  list: () => ipcRenderer.invoke("accounts:list"),
  add: () => ipcRenderer.invoke("accounts:add"),
  switchTo: (id) => ipcRenderer.invoke("accounts:switch", id),
  reload: (id) => ipcRenderer.invoke("accounts:reload", id),
  rename: (id, label) => ipcRenderer.invoke("accounts:rename", id, label),
  togglePin: (id) => ipcRenderer.invoke("accounts:togglePin", id),
  toggleMobile: (id) => ipcRenderer.invoke("accounts:toggleMobile", id),
  remove: (id) => ipcRenderer.invoke("accounts:remove", id),
  setLdIndex: (id, ldIndex) => ipcRenderer.invoke("accounts:setLdIndex", id, ldIndex),
  openInEmulator: (id) => ipcRenderer.invoke("accounts:openInEmulator", id),
  quitEmulator: (id) => ipcRenderer.invoke("accounts:quitEmulator", id),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  setSettings: (patch) => ipcRenderer.invoke("settings:set", patch),
  openPool: () => ipcRenderer.invoke("pool:openWindow"),
  onActiveChanged: (cb) => ipcRenderer.on("accounts:activeChanged", (_e, id) => cb(id)),
  onAccountsUpdated: (cb) => ipcRenderer.on("accounts:updated", (_e, accts) => cb(accts)),
});
