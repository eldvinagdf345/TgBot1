const { app, BrowserWindow, BrowserView, ipcMain, session, Menu } = require("electron");
const path = require("path");
const fs = require("fs");

const SIDEBAR_WIDTH = 84;
const TOPBAR_HEIGHT = 40;
const ACCOUNTS_FILE = path.join(app.getPath("userData"), "accounts.json");
const POOL_FILE = path.join(app.getPath("userData"), "pool.json");
const MOBILE_UA =
  "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36";

let mainWindow;
let poolWindow = null;
let accounts = [];
let poolLinks = [];
const views = new Map();
let activeAccountId = null;
let desktopUA = null;

// На части Windows-машин (виртуалки, RDP, старые/кривые видеодрайверы)
// GPU-процесс Chromium падает молча, и окно просто никогда не появляется
// без единой ошибки в консоли или в журнале событий Windows.
app.disableHardwareAcceleration();

const CRASH_LOG = path.join(app.getPath("userData"), "crash.log");
function logCrash(err) {
  try {
    fs.appendFileSync(CRASH_LOG, `${new Date().toISOString()} ${err?.stack || err}\n`);
  } catch {}
}
process.on("uncaughtException", logCrash);
process.on("unhandledRejection", logCrash);

function loadAccounts() {
  try {
    accounts = JSON.parse(fs.readFileSync(ACCOUNTS_FILE, "utf-8"));
  } catch {
    accounts = [];
  }
  accounts.forEach((a) => {
    if (a.pinned === undefined) a.pinned = false;
    if (a.mobileMode === undefined) a.mobileMode = false;
    if (a.visitCount === undefined) a.visitCount = 0;
  });
}

function saveAccounts() {
  fs.writeFileSync(ACCOUNTS_FILE, JSON.stringify(accounts, null, 2));
}

function loadPool() {
  try {
    poolLinks = JSON.parse(fs.readFileSync(POOL_FILE, "utf-8"));
  } catch {
    poolLinks = [];
  }
}

function savePool() {
  fs.writeFileSync(POOL_FILE, JSON.stringify(poolLinks, null, 2));
}

// Принимает голый ник, "@ник" или полную ссылку и приводит к виду
// https://www.instagram.com/ник/
function normalizeInstagramUrl(input) {
  let s = String(input || "").trim().replace(/^@/, "");
  if (/^https?:\/\//i.test(s)) return s;
  s = s.replace(/^(www\.)?instagram\.com\//i, "");
  s = s.split("/")[0].split("?")[0];
  return `https://www.instagram.com/${s}/`;
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
  view.setBounds({
    x: SIDEBAR_WIDTH,
    y: TOPBAR_HEIGHT,
    width: Math.max(w - SIDEBAR_WIDTH, 0),
    height: Math.max(h - TOPBAR_HEIGHT, 0),
  });
}

// Мобильный режим = мобильный вьюпорт + мобильный User-Agent + мобильная
// screen.orientation, аналог "Toggle device toolbar" в DevTools. Полезно,
// потому что у Instagram мобильная веб-версия заметно функциональнее в
// директе, чем десктопная.
//
// enableDeviceEmulation() из обычного webContents API подделывает только
// размер вьюпорта, а не screen.orientation — из-за этого Instagram при
// попытке выложить историю пишет "поверните устройство" (он проверяет
// именно системную ориентацию экрана, а не ширину/высоту окна). Поэтому
// эмуляция сделана через CDP напрямую (Emulation.setDeviceMetricsOverride
// с явным screenOrientation), это реально подделывает и то, и другое.
//
// disableDeviceEmulation-эквивалент вызываем только если эмуляция реально
// была включена раньше — на "чистом" view (никогда не включали) это на
// части Windows-машин роняло процесс на нативном уровне, минуя
// uncaughtException, поэтому симметрия enable/disable сохранена и здесь.
const emulatedViews = new WeakSet();

function applyMobileMode(view, enabled) {
  try {
    if (!desktopUA) desktopUA = view.webContents.getUserAgent();
    const dbg = view.webContents.debugger;

    if (enabled) {
      view.webContents.setUserAgent(MOBILE_UA);
      if (!dbg.isAttached()) dbg.attach("1.3");
      dbg
        .sendCommand("Emulation.setDeviceMetricsOverride", {
          width: 420,
          height: 900,
          deviceScaleFactor: 2,
          mobile: true,
          screenOrientation: { type: "portraitPrimary", angle: 0 },
        })
        .catch(logCrash);
      dbg
        .sendCommand("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 })
        .catch(logCrash);
      emulatedViews.add(view);
    } else if (emulatedViews.has(view)) {
      view.webContents.setUserAgent(desktopUA);
      if (dbg.isAttached()) {
        dbg.sendCommand("Emulation.clearDeviceMetricsOverride").catch(logCrash);
        dbg.sendCommand("Emulation.setTouchEmulationEnabled", { enabled: false }).catch(logCrash);
        dbg.detach();
      }
      emulatedViews.delete(view);
    }
  } catch (err) {
    logCrash(err);
  }
}

function ensureView(account) {
  if (views.has(account.id)) return views.get(account.id);
  // Отдельный partition на аккаунт = отдельные куки/логин, изолированные
  // друг от друга, как если бы каждый аккаунт открыт в своём браузерном
  // профиле.
  const view = new BrowserView({
    webPreferences: { partition: account.partition, contextIsolation: true },
  });
  views.set(account.id, view);
  if (account.mobileMode) {
    // enableDeviceEmulation на только что созданном view, у которого ещё
    // не было ни одной навигации, — судя по всему, ещё один способ уронить
    // процесс на этой машине так же тихо, как было с disableDeviceEmulation.
    // Откладываем до момента, когда страница реально начала грузиться.
    view.webContents.once("dom-ready", () => applyMobileMode(view, true));
  }
  view.webContents.loadURL("https://www.instagram.com/");
  return view;
}

function switchTo(accountId) {
  const account = accounts.find((a) => a.id === accountId);
  if (!account) return;
  const view = ensureView(account);
  mainWindow.setBrowserView(view);
  positionView(accountId);
  activeAccountId = accountId;
  // Переключение может прийти не из сайдбара (например, из окна пула) —
  // сайдбар должен узнать об этом сам, а не только тот, кто инициировал клик.
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("accounts:activeChanged", accountId);
  }
}

function broadcastAccounts() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("accounts:updated", accounts);
  }
}

function createPoolWindow() {
  if (poolWindow && !poolWindow.isDestroyed()) {
    poolWindow.show();
    poolWindow.focus();
    return;
  }
  poolWindow = new BrowserWindow({
    width: 320,
    height: 440,
    alwaysOnTop: true,
    title: "Пул клиентов",
    backgroundColor: "#0A0D14",
    webPreferences: {
      preload: path.join(__dirname, "pool-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  poolWindow.loadFile("pool-window.html");
  poolWindow.on("closed", () => {
    poolWindow = null;
  });
}

// Клик по ссылке в пуле: переключить главное окно на аккаунт с нужным
// номером и открыть в нём профиль клиента. Если такого номера среди
// подключённых аккаунтов нет — вернуть ошибку, ничего не переключая.
// Ссылка без привязанного номера открывается с текущего активного аккаунта.
function openPoolLink(id) {
  const link = poolLinks.find((l) => l.id === id);
  if (!link) return { ok: false, error: "Ссылка не найдена" };

  const hasTarget = link.targetNumber !== null && link.targetNumber !== undefined;
  const account = hasTarget
    ? accounts.find((a) => a.number === link.targetNumber)
    : accounts.find((a) => a.id === activeAccountId);

  if (!account) {
    return {
      ok: false,
      error: hasTarget ? `Аккаунт ${link.targetNumber} не подключен` : "Нет активного аккаунта",
    };
  }

  switchTo(account.id);
  const view = views.get(account.id);
  if (view) view.webContents.loadURL(normalizeInstagramUrl(link.url));
  mainWindow.show();
  mainWindow.focus();

  account.visitCount = (account.visitCount || 0) + 1;
  saveAccounts();
  broadcastAccounts();

  return { ok: true };
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  loadAccounts();
  loadPool();
  createWindow();
  if (accounts.length > 0) switchTo(accounts[0].id);
});

ipcMain.handle("accounts:list", () => accounts);

ipcMain.handle("accounts:add", () => {
  // Не accounts.length+1 — после удалений номера могли бы столкнуться
  // (пул привязывается именно к номеру, коллизия там недопустима).
  const number = accounts.reduce((max, a) => Math.max(max, a.number), 0) + 1;
  const id = `acct-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  accounts.push({
    id,
    number,
    label: `Аккаунт ${number}`,
    partition: `persist:${id}`,
    pinned: false,
    mobileMode: false,
    visitCount: 0,
  });
  saveAccounts();
  switchTo(id);
  return { accounts, activeAccountId };
});

ipcMain.handle("accounts:switch", (_e, accountId) => {
  switchTo(accountId);
  return activeAccountId;
});

ipcMain.handle("accounts:reload", (_e, accountId) => {
  const view = views.get(accountId);
  if (view) view.webContents.reload();
});

ipcMain.handle("accounts:rename", (_e, accountId, label) => {
  const account = accounts.find((a) => a.id === accountId);
  if (account) {
    account.label = label;
    saveAccounts();
  }
  return accounts;
});

ipcMain.handle("accounts:togglePin", (_e, accountId) => {
  const account = accounts.find((a) => a.id === accountId);
  if (account) {
    account.pinned = !account.pinned;
    saveAccounts();
  }
  return accounts;
});

ipcMain.handle("accounts:toggleMobile", (_e, accountId) => {
  const account = accounts.find((a) => a.id === accountId);
  if (!account) return accounts;
  account.mobileMode = !account.mobileMode;
  saveAccounts();
  const view = views.get(accountId);
  if (view) {
    applyMobileMode(view, account.mobileMode);
    view.webContents.reload();
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

ipcMain.handle("pool:list", () => poolLinks);

function normalizeTargetNumber(n) {
  return n === null || n === undefined || n === "" ? null : Number(n);
}

ipcMain.handle("pool:add", (_e, url, targetNumber) => {
  const id = `link-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  poolLinks.push({
    id,
    url: String(url).trim(),
    targetNumber: normalizeTargetNumber(targetNumber),
  });
  savePool();
  return poolLinks;
});

ipcMain.handle("pool:addBulk", (_e, items) => {
  items.forEach((item, i) => {
    const id = `link-${Date.now()}-${i}-${Math.random().toString(36).slice(2, 8)}`;
    poolLinks.push({
      id,
      url: String(item.url).trim(),
      targetNumber: normalizeTargetNumber(item.targetNumber),
    });
  });
  savePool();
  return poolLinks;
});

ipcMain.handle("pool:update", (_e, id, patch) => {
  const link = poolLinks.find((l) => l.id === id);
  if (link) {
    if (patch.url !== undefined) link.url = String(patch.url).trim();
    if (patch.targetNumber !== undefined) link.targetNumber = normalizeTargetNumber(patch.targetNumber);
    savePool();
  }
  return poolLinks;
});

ipcMain.handle("pool:remove", (_e, id) => {
  poolLinks = poolLinks.filter((l) => l.id !== id);
  savePool();
  return poolLinks;
});

ipcMain.handle("pool:open", (_e, id) => openPoolLink(id));

ipcMain.handle("pool:openWindow", () => {
  createPoolWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
