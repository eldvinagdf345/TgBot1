const { app, BrowserWindow, BrowserView, ipcMain, session, Menu, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const { execFile } = require("child_process");

const SIDEBAR_WIDTH = 84;
const TOPBAR_HEIGHT = 40;
const ACCOUNTS_FILE = path.join(app.getPath("userData"), "accounts.json");
const POOL_FILE = path.join(app.getPath("userData"), "pool.json");
const SETTINGS_FILE = path.join(app.getPath("userData"), "settings.json");
const MOBILE_UA =
  "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36";

let mainWindow;
let poolWindow = null;
let accounts = [];
let poolLinks = [];
let settings = { ldConsolePath: "" };
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
    if (a.ldIndex === undefined) a.ldIndex = null;
  });
}

function saveAccounts() {
  fs.writeFileSync(ACCOUNTS_FILE, JSON.stringify(accounts, null, 2));
}

function loadSettings() {
  try {
    settings = { ...settings, ...JSON.parse(fs.readFileSync(SETTINGS_FILE, "utf-8")) };
  } catch {
    // используем дефолт
  }
}

function saveSettings() {
  fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
}

function runLdconsole(args) {
  if (!settings.ldConsolePath) {
    return Promise.resolve({ ok: false, error: "Не задан путь к ldconsole.exe в настройках" });
  }
  return new Promise((resolve) => {
    execFile(settings.ldConsolePath, args, (err) => {
      if (err) {
        logCrash(err);
        resolve({ ok: false, error: `Команда LDPlayer не выполнена: ${err.message}` });
      } else {
        resolve({ ok: true });
      }
    });
  });
}

function accountLdIndexOrError(accountId) {
  const account = accounts.find((a) => a.id === accountId);
  if (!account) return { error: "Аккаунт не найден" };
  if (account.ldIndex === null || account.ldIndex === undefined) {
    return { error: "Для этого аккаунта не задан номер инстанса LDPlayer" };
  }
  return { ldIndex: account.ldIndex };
}

// Запускает конкретный инстанс LDPlayer (настоящее Android-приложение
// Instagram) по его индексу — для действий, которых веб-версия принципиально
// не может сделать (интерактивные стикеры вроде "Ссылки" в истории). Логин
// внутри инстанса делается вручную один раз и остаётся сохранённым, как на
// обычном телефоне — программа не хранит и не вводит пароли/2FA сама.
function openInEmulator(accountId) {
  const { ldIndex, error } = accountLdIndexOrError(accountId);
  if (error) return Promise.resolve({ ok: false, error });
  return runLdconsole(["launch", "--index", String(ldIndex)]);
}

// Останавливает инстанс — используется по желанию, если реально не хватает
// памяти. По умолчанию быстрее оставлять инстансы запущенными: следующий
// вход тогда мгновенный, без повторной холодной загрузки Android.
function quitEmulator(accountId) {
  const { ldIndex, error } = accountLdIndexOrError(accountId);
  if (error) return Promise.resolve({ ok: false, error });
  return runLdconsole(["quit", "--index", String(ldIndex)]);
}

// Запускает разом все аккаунты с привязанным номером LDPlayer — чтобы
// холодная загрузка Android шла параллельно в фоне у всех сразу, а не по
// очереди, пока ждёшь каждую перед тем, как постить историю.
function openAllInEmulators() {
  const withLd = accounts.filter((a) => a.ldIndex !== null && a.ldIndex !== undefined);
  if (withLd.length === 0) {
    return Promise.resolve({ ok: false, error: "Ни у одного аккаунта не задан номер инстанса LDPlayer" });
  }
  return Promise.all(withLd.map((a) => runLdconsole(["launch", "--index", String(a.ldIndex)]))).then(
    (results) => {
      const failed = results.filter((r) => !r.ok);
      if (failed.length > 0) {
        return { ok: false, error: `Не удалось запустить: ${failed.length} из ${withLd.length}` };
      }
      return { ok: true, count: withLd.length };
    }
  );
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

const MOBILE_VIEW_WIDTH = 420;

function positionView(accountId) {
  const view = views.get(accountId);
  if (!view) return;
  const account = accounts.find((a) => a.id === accountId);
  const [w, h] = mainWindow.getContentSize();
  const availWidth = Math.max(w - SIDEBAR_WIDTH, 0);
  const availHeight = Math.max(h - TOPBAR_HEIGHT, 0);

  if (account && account.mobileMode) {
    // Реально сужаем окно рендеринга, а не только подделываем цифры через
    // CDP — иначе настоящие пиксели окна (широкие, десктопные) не сходятся
    // с заявленной портретной ориентацией, и Instagram иногда всё равно
    // просит повернуть устройство.
    const mobileWidth = Math.min(MOBILE_VIEW_WIDTH, availWidth);
    view.setBounds({
      x: SIDEBAR_WIDTH + Math.floor((availWidth - mobileWidth) / 2),
      y: TOPBAR_HEIGHT,
      width: mobileWidth,
      height: availHeight,
    });
  } else {
    view.setBounds({ x: SIDEBAR_WIDTH, y: TOPBAR_HEIGHT, width: availWidth, height: availHeight });
  }
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
          width: MOBILE_VIEW_WIDTH,
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

// Экспорт/импорт cookies — чтобы быстро восстановить свою же сессию
// (например, после сброса partition или на новой машине), не проходя
// логин/пароль/2FA заново каждый раз. Работает с cookies текущей сессии
// аккаунта, никак не завязано на сторонние/чужие аккаунты.
async function exportCookies(accountId) {
  const account = accounts.find((a) => a.id === accountId);
  if (!account) return { ok: false, error: "Аккаунт не найден" };

  const ses = session.fromPartition(account.partition);
  const cookies = await ses.cookies.get({ domain: "instagram.com" });
  if (cookies.length === 0) {
    return { ok: false, error: "У этого аккаунта нет сохранённых cookies — сначала залогинься." };
  }

  const { canceled, filePath } = await dialog.showSaveDialog(mainWindow, {
    title: "Сохранить cookies",
    defaultPath: `${account.label.replace(/[^\w-]+/g, "_")}-cookies.json`,
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (canceled || !filePath) return { ok: false, error: "Отменено" };

  fs.writeFileSync(filePath, JSON.stringify(cookies, null, 2));
  return { ok: true, filePath, count: cookies.length };
}

async function pickCookiesFile() {
  const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
    title: "Выбери файл с cookies",
    filters: [{ name: "JSON / текст", extensions: ["json", "txt"] }],
    properties: ["openFile"],
  });
  if (canceled || filePaths.length === 0) return { ok: false, error: "Отменено" };
  try {
    return { ok: true, text: fs.readFileSync(filePaths[0], "utf-8") };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

// Принимает либо JSON-массив (наш экспорт, Cookie-Editor и т.п.), либо
// обычную строку вида "name1=value1; name2=value2; ..." — так cookies
// чаще всего копируют вручную откуда угодно (DevTools, другой источник).
function parseCookiesInput(text) {
  const trimmed = text.trim();
  if (!trimmed) return [];

  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed)) return parsed;
  } catch {
    // не JSON — разбираем как строку "name=value; name=value"
  }

  return trimmed
    .split(";")
    .map((pair) => pair.trim())
    .filter(Boolean)
    .map((pair) => {
      const idx = pair.indexOf("=");
      if (idx === -1) return null;
      const name = pair.slice(0, idx).trim();
      const value = pair.slice(idx + 1).trim();
      return name ? { name, value } : null;
    })
    .filter(Boolean);
}

async function importCookiesFromText(accountId, text) {
  const account = accounts.find((a) => a.id === accountId);
  if (!account) return { ok: false, error: "Аккаунт не найден" };

  const cookies = parseCookiesInput(text);
  if (cookies.length === 0) {
    return { ok: false, error: "Не удалось распознать ни одной cookie в тексте" };
  }

  const ses = session.fromPartition(account.partition);
  let imported = 0;
  for (const c of cookies) {
    try {
      const secure = c.secure !== false;
      const protocol = secure ? "https:" : "http:";
      const domain = String(c.domain || "instagram.com").replace(/^\./, "");
      const setDetails = {
        url: `${protocol}//${domain}${c.path || "/"}`,
        name: c.name,
        value: c.value,
        domain: c.domain || `.${domain}`,
        path: c.path || "/",
        secure,
        httpOnly: !!c.httpOnly,
      };
      if (c.sameSite) setDetails.sameSite = c.sameSite;
      if (!c.session && c.expirationDate) setDetails.expirationDate = c.expirationDate;
      await ses.cookies.set(setDetails);
      imported++;
    } catch (err) {
      logCrash(err);
    }
  }

  const view = views.get(accountId);
  if (view) view.webContents.reload();

  return { ok: true, imported };
}

// BrowserView рисуется отдельным нативным слоем поверх всей страницы
// независимо от CSS/z-index — оверлеи вроде контекстного меню, вылезающие
// за пределы узкой боковой панели, им перекрывает. Прячем на время оверлея.
function setBrowserViewVisible(visible) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (visible) {
    if (activeAccountId) {
      const view = views.get(activeAccountId);
      if (view) {
        mainWindow.setBrowserView(view);
        positionView(activeAccountId);
      }
    }
  } else {
    mainWindow.setBrowserView(null);
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
  loadSettings();
  createWindow();
  if (accounts.length > 0) switchTo(accounts[0].id);
});

ipcMain.handle("browserview:setVisible", (_e, visible) => {
  setBrowserViewVisible(visible);
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
    positionView(accountId);
    view.webContents.reload();
  }
  return accounts;
});

ipcMain.handle("accounts:setLdIndex", (_e, accountId, ldIndex) => {
  const account = accounts.find((a) => a.id === accountId);
  if (account) {
    account.ldIndex = ldIndex === null || ldIndex === "" ? null : Number(ldIndex);
    saveAccounts();
  }
  return accounts;
});

ipcMain.handle("accounts:exportCookies", (_e, accountId) => exportCookies(accountId));
ipcMain.handle("accounts:pickCookiesFile", () => pickCookiesFile());
ipcMain.handle("accounts:importCookiesText", (_e, accountId, text) => importCookiesFromText(accountId, text));

ipcMain.handle("accounts:openInEmulator", (_e, accountId) => openInEmulator(accountId));
ipcMain.handle("accounts:quitEmulator", (_e, accountId) => quitEmulator(accountId));
ipcMain.handle("accounts:openAllInEmulators", () => openAllInEmulators());

ipcMain.handle("settings:get", () => settings);

ipcMain.handle("settings:set", (_e, patch) => {
  settings = { ...settings, ...patch };
  saveSettings();
  return settings;
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
