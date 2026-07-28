const { app, BrowserWindow, BrowserView, ipcMain, session } = require("electron");
const path = require("path");
const fs = require("fs");

const SIDEBAR_WIDTH = 84;
const ACCOUNTS_FILE = path.join(app.getPath("userData"), "accounts.json");

let mainWindow;
let accounts = [];
const views = new Map();
let activeAccountId = null;

function loadAccounts() {
  try {
    accounts = JSON.parse(fs.readFileSync(ACCOUNTS_FILE, "utf-8"));
  } catch {
    accounts = [];
  }
}

function saveAccounts() {
  fs.writeFileSync(ACCOUNTS_FILE, JSON.stringify(accounts, null, 2));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 720,
    minHeight: 480,
    backgroundColor: "#0A0D14",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile("index.html");
  mainWindow.on("resize", () => {
    if (activeAccountId) positionView(activeAccountId);
  });
}

function positionView(accountId) {
  const view = views.get(accountId);
  if (!view) return;
  const [w, h] = mainWindow.getContentSize();
  view.setBounds({ x: SIDEBAR_WIDTH, y: 0, width: Math.max(w - SIDEBAR_WIDTH, 0), height: h });
}

function ensureView(account) {
  if (views.has(account.id)) return views.get(account.id);
  // Отдельный partition на аккаунт = отдельные куки/логин, изолированные
  // друг от друга, как если бы каждый аккаунт открыт в своём браузерном
  // профиле.
  const view = new BrowserView({
    webPreferences: { partition: account.partition, contextIsolation: true },
  });
  view.webContents.loadURL("https://www.instagram.com/");
  views.set(account.id, view);
  return view;
}

function switchTo(accountId) {
  const account = accounts.find((a) => a.id === accountId);
  if (!account) return;
  const view = ensureView(account);
  mainWindow.setBrowserView(view);
  positionView(accountId);
  activeAccountId = accountId;
}

app.whenReady().then(() => {
  loadAccounts();
  createWindow();
  if (accounts.length > 0) switchTo(accounts[0].id);
});

ipcMain.handle("accounts:list", () => accounts);

ipcMain.handle("accounts:add", () => {
  const number = accounts.length + 1;
  const id = `acct-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  accounts.push({ id, number, label: `Аккаунт ${number}`, partition: `persist:${id}` });
  saveAccounts();
  switchTo(id);
  return { accounts, activeAccountId };
});

ipcMain.handle("accounts:switch", (_e, accountId) => {
  switchTo(accountId);
  return activeAccountId;
});

ipcMain.handle("accounts:rename", (_e, accountId, label) => {
  const account = accounts.find((a) => a.id === accountId);
  if (account) {
    account.label = label;
    saveAccounts();
  }
  return accounts;
});

ipcMain.handle("accounts:remove", async (_e, accountId) => {
  const account = accounts.find((a) => a.id === accountId);
  if (!account) return { accounts, activeAccountId };

  const view = views.get(accountId);
  if (view) {
    if (mainWindow.getBrowserView() === view) mainWindow.setBrowserView(null);
    await session.fromPartition(account.partition).clearStorageData();
    view.webContents.destroy();
    views.delete(accountId);
  }

  accounts = accounts.filter((a) => a.id !== accountId);
  saveAccounts();

  if (activeAccountId === accountId) {
    activeAccountId = null;
    if (accounts.length > 0) switchTo(accounts[0].id);
  }
  return { accounts, activeAccountId };
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
