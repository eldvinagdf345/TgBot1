function showStatus(text) {
  let el = document.getElementById("poolStatus");
  if (!el) {
    el = document.createElement("div");
    el.id = "poolStatus";
    el.className = "pool-status";
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.style.opacity = "1";
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => (el.style.opacity = "0"), 3000);
}

async function render() {
  const links = await window.poolAPI.list();
  const list = document.getElementById("poolList");
  list.innerHTML = "";

  if (links.length === 0) {
    list.innerHTML = '<div class="pool-empty">Пул пуст. Добавь ссылку снизу.</div>';
    return;
  }

  links.forEach((link) => {
    const row = document.createElement("div");
    row.className = "pool-item";

    const label = document.createElement("span");
    label.className = "pool-label";
    label.textContent = link.url;
    label.title = "Клик — открыть, двойной клик — изменить";

    const badge = document.createElement("span");
    badge.className = "pool-badge";
    badge.textContent = `#${link.targetNumber}`;

    const delBtn = document.createElement("button");
    delBtn.className = "pool-del";
    delBtn.textContent = "×";
    delBtn.title = "Удалить";

    row.appendChild(label);
    row.appendChild(badge);
    row.appendChild(delBtn);

    row.addEventListener("click", async (e) => {
      if (e.target === delBtn) return;
      const res = await window.poolAPI.open(link.id);
      if (!res.ok) showStatus(res.error);
    });

    row.addEventListener("dblclick", async (e) => {
      e.stopPropagation();
      const newUrl = prompt("Ник/ссылка:", link.url);
      if (newUrl === null) return;
      const newNum = prompt("Номер аккаунта:", link.targetNumber);
      if (newNum === null) return;
      await window.poolAPI.update(link.id, { url: newUrl.trim(), targetNumber: Number(newNum) });
      render();
    });

    delBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await window.poolAPI.remove(link.id);
      render();
    });

    list.appendChild(row);
  });
}

document.getElementById("poolAddBtn").addEventListener("click", async () => {
  const urlInput = document.getElementById("poolUrlInput");
  const numInput = document.getElementById("poolNumInput");
  const url = urlInput.value.trim();
  const num = Number(numInput.value);
  if (!url || !num) {
    showStatus("Укажи ссылку и номер аккаунта");
    return;
  }
  await window.poolAPI.add(url, num);
  urlInput.value = "";
  numInput.value = "";
  render();
});

render();
