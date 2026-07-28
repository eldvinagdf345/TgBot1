let accounts = [];
let activeId = null;
let ctxAccountId = null;

function sortedAccounts() {
  // Закреплённые — в начале, порядок внутри групп как в исходном массиве.
  return [...accounts].sort((a, b) => (b.pinned === true) - (a.pinned === true));
}

function render() {
  const list = document.getElementById("accountList");
  list.innerHTML = "";

  sortedAccounts().forEach((acc) => {
    const item = document.createElement("div");
    item.className = "slot" + (acc.id === activeId ? " active" : "");
    item.textContent = acc.number;
    item.title = acc.label;

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
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.hidden = false;
}

function closeCtxMenu() {
  document.getElementById("ctxMenu").hidden = true;
  ctxAccountId = null;
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

document.getElementById("mobileToggleBtn").addEventListener("click", async () => {
  if (!activeId) return;
  accounts = await window.accountsAPI.toggleMobile(activeId);
  renderTopbar();
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

(async () => {
  accounts = await window.accountsAPI.list();
  if (accounts.length > 0) activeId = accounts[0].id;
  render();
  renderTopbar();
})();
