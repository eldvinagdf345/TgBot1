async function render() {
  const { profiles = [] } = await chrome.storage.local.get("profiles");
  const list = document.getElementById("list");
  list.innerHTML = "";
  document.getElementById("count").textContent = profiles.length;

  if (profiles.length === 0) {
    list.innerHTML = '<li class="empty">Пока пусто. Открой пару профилей в Instagram.</li>';
    return;
  }

  for (const p of profiles.slice().reverse()) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.className = "chk";
    chk.value = p.username;
    chk.checked = true;
    label.appendChild(chk);
    label.appendChild(document.createTextNode(`@${p.username}`));
    li.appendChild(label);
    list.appendChild(li);
  }
}

function selectedUsernames() {
  return Array.from(document.querySelectorAll(".chk:checked")).map((el) => el.value);
}

function setStatus(text) {
  document.getElementById("status").textContent = text;
}

document.getElementById("sendBtn").addEventListener("click", async () => {
  const usernames = selectedUsernames();
  if (usernames.length === 0) {
    setStatus("Список пуст.");
    return;
  }
  setStatus("Отправляю...");
  const res = await chrome.runtime.sendMessage({ type: "SEND_TO_TELEGRAM", usernames });
  setStatus(res.ok ? "✅ Отправлено в Telegram" : `❌ ${res.error}`);
});

document.getElementById("copyBtn").addEventListener("click", async () => {
  const usernames = selectedUsernames();
  if (usernames.length === 0) {
    setStatus("Список пуст.");
    return;
  }
  await navigator.clipboard.writeText(usernames.map((u) => `@${u}`).join("\n"));
  setStatus("📋 Скопировано в буфер обмена");
});

document.getElementById("clearBtn").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "CLEAR_PROFILES" });
  setStatus("Список очищен");
  render();
});

document.getElementById("optionsBtn").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

render();
