let accounts = [];
let activeId = null;

function render() {
  const list = document.getElementById("accountList");
  list.innerHTML = "";

  accounts.forEach((acc) => {
    const item = document.createElement("div");
    item.className = "slot" + (acc.id === activeId ? " active" : "");
    item.textContent = acc.number;
    item.title = `${acc.label} (двойной клик — переименовать, правый клик — удалить)`;

    item.addEventListener("click", async () => {
      activeId = await window.accountsAPI.switchTo(acc.id);
      render();
    });

    item.addEventListener("dblclick", async (e) => {
      e.stopPropagation();
      const newLabel = prompt("Название аккаунта:", acc.label);
      if (newLabel && newLabel.trim()) {
        accounts = await window.accountsAPI.rename(acc.id, newLabel.trim());
        render();
      }
    });

    item.addEventListener("contextmenu", async (e) => {
      e.preventDefault();
      if (confirm(`Удалить "${acc.label}"? Сессия (логин) будет забыта.`)) {
        const res = await window.accountsAPI.remove(acc.id);
        accounts = res.accounts;
        activeId = res.activeAccountId;
        render();
      }
    });

    list.appendChild(item);
  });
}

document.getElementById("addBtn").addEventListener("click", async () => {
  const res = await window.accountsAPI.add();
  accounts = res.accounts;
  activeId = res.activeAccountId;
  render();
});

(async () => {
  accounts = await window.accountsAPI.list();
  if (accounts.length > 0) activeId = accounts[0].id;
  render();
})();
