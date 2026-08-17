let accounts = [];
let activeId = null;
let ctxAccountId = null;

function sortedAccounts() {
  // Закреплённые — в начале, порядок внутри групп как в исходном массиве.
  return [...accounts].sort((a, b) => (b.pinned === true) - (a.pinned === true));
}

function countClass(n) {
  if (n >= 10) return "count-red";
  if (n >= 6) return "count-orange";
  return "count-green";
}

function render() {
  const list = document.getElementById("accountList");
  list.innerHTML = "";

  sortedAccounts().forEach((acc) => {
    const item = document.createElement("div");
    item.className = "slot" + (acc.id === activeId ? " active" : "");
    item.title = acc.label;

    const numberEl = document.createElement("div");
    numberEl.className = "slot-number";
    numberEl.textContent = acc.number;
    item.appendChild(numberEl);

    const divider = document.createElement("div");
    divider.className = "slot-divider";
    item.appendChild(divider);

    const count = acc.visitCount || 0;
    const countEl = document.createElement("div");
    countEl.className = `slot-count ${countClass(count)}`;
    countEl.textContent = count;
    item.appendChild(countEl);

    if (acc.pinned) {
      const pin = document.createElement("span");
      pin.className = "pin-dot";
      pin.textContent = "📌";
      item.appendChild(pin);
    }

    item.addEventListener("click", async () => {
      activeId = await window.accountsAPI.switchTo(acc.id);
      render();
      renderTopbar();
    });

    item.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      openRenameModal(acc.id, acc.label);
    });

    item.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      openCtxMenu(e.clientX, e.clientY, acc);
    });

    list.appendChild(item);
  });
}

function openCtxMenu(x, y, acc) {
  ctxAccountId = acc.id;
  const menu = document.getElementById("ctxMenu");
  document.getElementById("ctxPin").textContent = acc.pinned ? "📌 Открепить" : "📌 Закрепить";
  const hasLd = acc.ldIndex !== null && acc.ldIndex !== undefined;
  document.getElementById("ctxLdIndex").textContent = hasLd
    ? `📲 Номер инстанса LDPlayer: ${acc.ldIndex}`
    : "📲 Номер инстанса LDPlayer…";
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.hidden = false;
  // BrowserView (сам Instagram) рисуется поверх страницы и перекрывает
  // меню, если оно вылезает за пределы узкой боковой панели.
  window.accountsAPI.setBrowserViewVisible(false);
}

function closeCtxMenu() {
  document.getElementById("ctxMenu").hidden = true;
  ctxAccountId = null;
  window.accountsAPI.setBrowserViewVisible(true);
}

document.addEventListener("click", (e) => {
  const menu = document.getElementById("ctxMenu");
  if (!menu.hidden && !menu.contains(e.target)) closeCtxMenu();
});

document.getElementById("ctxPin").addEventListener("click", async () => {
  if (!ctxAccountId) return;
  accounts = await window.accountsAPI.togglePin(ctxAccountId);
  closeCtxMenu();
  render();
});

// --- Переименование аккаунта (модалка вместо window.prompt) ---

let renameTargetId = null;

function openRenameModal(accountId, currentLabel) {
  renameTargetId = accountId;
  document.getElementById("renameInput").value = currentLabel;
  document.getElementById("renameModal").hidden = false;
  window.accountsAPI.setBrowserViewVisible(false);
}

function closeRenameModal() {
  document.getElementById("renameModal").hidden = true;
  renameTargetId = null;
  window.accountsAPI.setBrowserViewVisible(true);
}

document.getElementById("renameSaveBtn").addEventListener("click", async () => {
  if (!renameTargetId) return;
  const targetId = renameTargetId;
  const label = document.getElementById("renameInput").value.trim();
  closeRenameModal();
  if (label) {
    accounts = await window.accountsAPI.rename(targetId, label);
    render();
    renderTopbar();
  }
});

document.getElementById("renameCancelBtn").addEventListener("click", closeRenameModal);

// --- Номер инстанса LDPlayer (модалка вместо window.prompt) ---

let ldIndexTargetId = null;

function openLdIndexModal(accountId) {
  ldIndexTargetId = accountId;
  const acc = accounts.find((a) => a.id === accountId);
  document.getElementById("ldIndexInput").value =
    acc && acc.ldIndex !== null && acc.ldIndex !== undefined ? acc.ldIndex : "";
  document.getElementById("ldIndexModal").hidden = false;
  window.accountsAPI.setBrowserViewVisible(false);
}

function closeLdIndexModal() {
  document.getElementById("ldIndexModal").hidden = true;
  ldIndexTargetId = null;
  window.accountsAPI.setBrowserViewVisible(true);
}

document.getElementById("ctxLdIndex").addEventListener("click", () => {
  if (!ctxAccountId) return;
  const targetId = ctxAccountId; // closeCtxMenu() ниже обнуляет ctxAccountId
  closeCtxMenu();
  openLdIndexModal(targetId);
});

document.getElementById("ldIndexSaveBtn").addEventListener("click", async () => {
  if (!ldIndexTargetId) return;
  const targetId = ldIndexTargetId;
  const raw = document.getElementById("ldIndexInput").value.trim();
  accounts = await window.accountsAPI.setLdIndex(targetId, raw === "" ? null : raw);
  closeLdIndexModal();
  render();
});

document.getElementById("ldIndexClearBtn").addEventListener("click", async () => {
  if (!ldIndexTargetId) return;
  const targetId = ldIndexTargetId;
  accounts = await window.accountsAPI.setLdIndex(targetId, null);
  closeLdIndexModal();
  render();
});

document.getElementById("ldIndexCancelBtn").addEventListener("click", () => {
  closeLdIndexModal();
});

// --- Экспорт/импорт cookies ---

document.getElementById("ctxExportCookies").addEventListener("click", async () => {
  if (!ctxAccountId) return;
  const targetId = ctxAccountId;
  closeCtxMenu();
  const res = await window.accountsAPI.exportCookies(targetId);
  if (res.error === "Отменено") return;
  alert(res.ok ? `Сохранено (${res.count} cookies): ${res.filePath}` : `❌ ${res.error}`);
});

let cookiesImportTargetId = null;

function openCookiesImportModal(accountId) {
  cookiesImportTargetId = accountId;
  document.getElementById("cookiesImportInput").value = "";
  document.getElementById("cookiesImportModal").hidden = false;
  window.accountsAPI.setBrowserViewVisible(false);
}

function closeCookiesImportModal() {
  document.getElementById("cookiesImportModal").hidden = true;
  cookiesImportTargetId = null;
  window.accountsAPI.setBrowserViewVisible(true);
}

document.getElementById("ctxImportCookies").addEventListener("click", () => {
  if (!ctxAccountId) return;
  const targetId = ctxAccountId;
  closeCtxMenu();
  openCookiesImportModal(targetId);
});

document.getElementById("cookiesImportCancelBtn").addEventListener("click", closeCookiesImportModal);

document.getElementById("cookiesPickFileBtn").addEventListener("click", async () => {
  const res = await window.accountsAPI.pickCookiesFile();
  if (res.ok) document.getElementById("cookiesImportInput").value = res.text;
});

document.getElementById("cookiesImportSaveBtn").addEventListener("click", async () => {
  if (!cookiesImportTargetId) return;
  const targetId = cookiesImportTargetId;
  const text = document.getElementById("cookiesImportInput").value;
  if (!text.trim()) {
    alert("Вставь текст cookies или выбери файл.");
    return;
  }
  closeCookiesImportModal();
  const res = await window.accountsAPI.importCookiesText(targetId, text);
  if (!res.ok) {
    alert(`❌ ${res.error}`);
    return;
  }
  const failuresText = res.failures?.length ? `\n\nОшибки:\n${res.failures.join("\n")}` : "";
  alert(
    `Импортировано: ${res.imported} из ${res.total}.${failuresText}\nОбнови страницу (🔄), если логин не виден.`
  );
});

// --- Общая модалка подтверждения (вместо window.confirm) ---

let confirmCallback = null;

function openConfirmModal(message, onYes) {
  document.getElementById("confirmMessage").textContent = message;
  confirmCallback = onYes;
  document.getElementById("confirmModal").hidden = false;
  window.accountsAPI.setBrowserViewVisible(false);
}

function closeConfirmModal() {
  document.getElementById("confirmModal").hidden = true;
  confirmCallback = null;
  window.accountsAPI.setBrowserViewVisible(true);
}

document.getElementById("confirmYesBtn").addEventListener("click", () => {
  const cb = confirmCallback;
  closeConfirmModal();
  if (cb) cb();
});

document.getElementById("confirmNoBtn").addEventListener("click", closeConfirmModal);

document.getElementById("ctxDelete").addEventListener("click", () => {
  if (!ctxAccountId) return;
  const targetId = ctxAccountId;
  const acc = accounts.find((a) => a.id === targetId);
  closeCtxMenu();
  if (!acc) return;
  openConfirmModal(`Удалить "${acc.label}"? Сессия (логин) будет забыта.`, async () => {
    const res = await window.accountsAPI.remove(targetId);
    accounts = res.accounts;
    activeId = res.activeAccountId;
    render();
    renderTopbar();
  });
});

function renderTopbar() {
  const acc = accounts.find((a) => a.id === activeId);
  document.getElementById("activeLabel").textContent = acc ? acc.label : "";
  const btn = document.getElementById("mobileToggleBtn");
  btn.classList.toggle("active", !!acc?.mobileMode);
}

document.getElementById("reloadBtn").addEventListener("click", () => {
  if (activeId) window.accountsAPI.reload(activeId);
});

document.getElementById("mobileToggleBtn").addEventListener("click", async () => {
  if (!activeId) return;
  accounts = await window.accountsAPI.toggleMobile(activeId);
  renderTopbar();
});

// --- Путь к ldconsole.exe (модалка вместо window.prompt) ---

let pendingEmulatorOpen = null;

function openSettingsModal() {
  document.getElementById("ldPathInput").value = "C:\\LDPlayer\\LDPlayer9\\ldconsole.exe";
  document.getElementById("settingsModal").hidden = false;
  window.accountsAPI.setBrowserViewVisible(false);
}

function closeSettingsModal() {
  document.getElementById("settingsModal").hidden = true;
  window.accountsAPI.setBrowserViewVisible(true);
}

document.getElementById("settingsCancelBtn").addEventListener("click", () => {
  pendingEmulatorOpen = null;
  closeSettingsModal();
});

document.getElementById("settingsSaveBtn").addEventListener("click", async () => {
  const path = document.getElementById("ldPathInput").value.trim();
  if (!path) return;
  await window.accountsAPI.setSettings({ ldConsolePath: path });
  closeSettingsModal();
  if (pendingEmulatorOpen === "ALL") {
    pendingEmulatorOpen = null;
    const res = await window.accountsAPI.openAllInEmulators();
    alert(res.ok ? `Запущено: ${res.count}` : res.error);
  } else if (pendingEmulatorOpen) {
    const id = pendingEmulatorOpen;
    pendingEmulatorOpen = null;
    const res = await window.accountsAPI.openInEmulator(id);
    if (!res.ok) alert(res.error);
  }
});

document.getElementById("emulatorBtn").addEventListener("click", async () => {
  if (!activeId) return;

  const acc = accounts.find((a) => a.id === activeId);
  if (!acc || acc.ldIndex === null || acc.ldIndex === undefined) {
    alert(
      'У этого аккаунта не задан номер инстанса LDPlayer.\nПравый клик по слоту → "📲 Номер инстанса LDPlayer…"'
    );
    return;
  }

  const settings = await window.accountsAPI.getSettings();
  if (!settings.ldConsolePath) {
    pendingEmulatorOpen = activeId;
    openSettingsModal();
    return;
  }

  const res = await window.accountsAPI.openInEmulator(activeId);
  if (!res.ok) alert(res.error);
});

document.getElementById("emulatorQuitBtn").addEventListener("click", async () => {
  if (!activeId) return;
  const res = await window.accountsAPI.quitEmulator(activeId);
  if (!res.ok) alert(res.error);
});

document.getElementById("addBtn").addEventListener("click", async () => {
  const res = await window.accountsAPI.add();
  accounts = res.accounts;
  activeId = res.activeAccountId;
  render();
  renderTopbar();
});

document.getElementById("poolBtn").addEventListener("click", () => {
  window.accountsAPI.openPool();
});

document.getElementById("launchAllBtn").addEventListener("click", async () => {
  const settings = await window.accountsAPI.getSettings();
  if (!settings.ldConsolePath) {
    pendingEmulatorOpen = "ALL";
    openSettingsModal();
    return;
  }
  const res = await window.accountsAPI.openAllInEmulators();
  alert(res.ok ? `Запущено: ${res.count}` : res.error);
});

window.accountsAPI.onActiveChanged((id) => {
  activeId = id;
  render();
  renderTopbar();
});

window.accountsAPI.onAccountsUpdated((accts) => {
  accounts = accts;
  render();
  renderTopbar();
});

(async () => {
  accounts = await window.accountsAPI.list();
  if (accounts.length > 0) activeId = accounts[0].id;
  render();
  renderTopbar();
})();
