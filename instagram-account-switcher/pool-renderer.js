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
    list.innerHTML = '<div class="pool-empty">Пул пуст. Добавь ссылки снизу.</div>';
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
    const hasTarget = link.targetNumber !== null && link.targetNumber !== undefined;
    badge.className = "pool-badge" + (hasTarget ? "" : " pool-badge-muted");
    badge.textContent = hasTarget ? `#${link.targetNumber}` : "тек.";
    badge.title = hasTarget
      ? `Откроется с аккаунта №${link.targetNumber}`
      : "Откроется с текущего активного аккаунта";

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

    row.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      openEditModal(link);
    });

    delBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await window.poolAPI.remove(link.id);
      render();
    });

    list.appendChild(row);
  });
}

// --- Редактирование ссылки (модалка вместо window.prompt) ---

let editTargetId = null;

function openEditModal(link) {
  editTargetId = link.id;
  document.getElementById("editUrlInput").value = link.url;
  const hasTarget = link.targetNumber !== null && link.targetNumber !== undefined;
  document.getElementById("editNumInput").value = hasTarget ? link.targetNumber : "";
  document.getElementById("editModal").hidden = false;
}

function closeEditModal() {
  document.getElementById("editModal").hidden = true;
  editTargetId = null;
}

document.getElementById("editCancelBtn").addEventListener("click", closeEditModal);

document.getElementById("editSaveBtn").addEventListener("click", async () => {
  if (!editTargetId) return;
  const targetId = editTargetId;
  const url = document.getElementById("editUrlInput").value.trim();
  const numRaw = document.getElementById("editNumInput").value.trim();
  closeEditModal();
  if (!url) return;
  await window.poolAPI.update(targetId, { url, targetNumber: numRaw === "" ? null : Number(numRaw) });
  render();
});

document.getElementById("poolAddBtn").addEventListener("click", async () => {
  const urlInput = document.getElementById("poolUrlInput");
  const numInput = document.getElementById("poolNumInput");
  const url = urlInput.value.trim();
  const numRaw = numInput.value.trim();
  if (!url) {
    showStatus("Укажи ссылку");
    return;
  }
  const num = numRaw === "" ? null : Number(numRaw);
  await window.poolAPI.add(url, num);
  urlInput.value = "";
  numInput.value = "";
  render();
});

document.getElementById("bulkToggleBtn").addEventListener("click", () => {
  document.getElementById("bulkPanel").hidden = !document.getElementById("bulkPanel").hidden;
});

document.getElementById("bulkCancelBtn").addEventListener("click", () => {
  document.getElementById("bulkPanel").hidden = true;
});

document.getElementById("bulkAddBtn").addEventListener("click", async () => {
  const linksRaw = document.getElementById("bulkLinks").value;
  const numsRaw = document.getElementById("bulkNumbers").value;

  const links = linksRaw
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  const nums = numsRaw.split(/\r?\n/).map((s) => s.trim());

  if (links.length === 0) {
    showStatus("Список ссылок пуст");
    return;
  }

  // Номера привязываются к ссылкам по порядку — N-я строка номеров к N-й
  // ссылке. Если номеров меньше или строка пустая — эта ссылка остаётся
  // без привязки (откроется с текущего активного аккаунта).
  const items = links.map((url, i) => ({
    url,
    targetNumber: nums[i] && nums[i] !== "" ? Number(nums[i]) : null,
  }));

  await window.poolAPI.addBulk(items);
  document.getElementById("bulkLinks").value = "";
  document.getElementById("bulkNumbers").value = "";
  document.getElementById("bulkPanel").hidden = true;
  render();
});

render();
