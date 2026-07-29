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

    item.addEventListener("dblclick", async (e) => {
      e.stopPropagation();
      const newLabel = prompt("Название аккаунта:", acc.label);
      if (newLabel && newLabel.trim()) {
        accounts = await window.accountsAPI.rename(acc.id, newLabel.trim());
        render();
        renderTopbar();
      }
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

document.getElementById("ctxLdIndex").addEventListener("click", async () => {
  if (!ctxAccountId) return;
  const acc = accounts.find((a) => a.id === ctxAccountId);
  closeCtxMenu();
  const raw = prompt(
    "Номер инстанса LDPlayer для этого аккаунта (--index в ldconsole.exe), пусто — снять привязку:",
    acc && acc.ldIndex !== null && acc.ldIndex !== undefined ? String(acc.ldIndex) : ""
  );
  if (raw === null) return;
  accounts = await window.accountsAPI.setLdIndex(ctxAccountId, raw.trim() === "" ? null : raw.trim());
  render();
});

document.getElementById("ctxDelete").addEventListener("click", async () => {
  if (!ctxAccountId) return;
  const acc = accounts.find((a) => a.id === ctxAccountId);
  closeCtxMenu();
  if (acc && confirm(`Удалить "${acc.label}"? Сессия (логин) будет забыта.`)) {
    const res = await window.accountsAPI.remove(acc.id);
    accounts = res.accounts;
    activeId = res.activeAccountId;
    render();
    renderTopbar();
  }
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
    const path = prompt(
      "Укажи путь к ldconsole.exe (обычно C:\\LDPlayer\\LDPlayer9\\ldconsole.exe):",
      "C:\\LDPlayer\\LDPlayer9\\ldconsole.exe"
    );
    if (!path) return;
    await window.accountsAPI.setSettings({ ldConsolePath: path.trim() });
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
