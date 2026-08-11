async function render() {
  const { profiles = [] } = await chrome.storage.local.get("profiles");
  const list = document.getElementById("list");
  list.innerHTML = "";
  document.getElementById("count").textContent = profiles.length;

  if (profiles.length === 0) {
    list.innerHTML = '<li class="empty">Пока пусто. Открой пару профилей в Instagram или Threads.</li>';
    return;
  }

  for (const p of profiles.slice().reverse()) {
    const platform = p.platform || "instagram";
    const li = document.createElement("li");
    const label = document.createElement("label");
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.className = "chk";
    chk.value = p.username;
    chk.dataset.platform = platform;
    chk.checked = true;
    label.appendChild(chk);
    const badge = document.createElement("span");
    badge.className = `platform-badge platform-${platform}`;
    badge.textContent = platform === "threads" ? "TH" : "IG";
    label.appendChild(badge);
    label.appendChild(document.createTextNode(`@${p.username}`));
    li.appendChild(label);
    list.appendChild(li);
  }
}

function selectedProfiles() {
  return Array.from(document.querySelectorAll(".chk:checked")).map((el) => ({
    username: el.value,
    platform: el.dataset.platform || "instagram",
  }));
}

function setStatus(text) {
  document.getElementById("status").textContent = text;
}

document.getElementById("sendBtn").addEventListener("click", async () => {
  const profiles = selectedProfiles();
  if (profiles.length === 0) {
    setStatus("Список пуст.");
    return;
  }
  setStatus("Отправляю...");
  const res = await chrome.runtime.sendMessage({ type: "SEND_TO_TELEGRAM", profiles });
  setStatus(res.ok ? "✅ Отправлено в Telegram" : `❌ ${res.error}`);
});

document.getElementById("copyBtn").addEventListener("click", async () => {
  const profiles = selectedProfiles();
  if (profiles.length === 0) {
    setStatus("Список пуст.");
    return;
  }
  await navigator.clipboard.writeText(profiles.map((p) => `@${p.username}`).join("\n"));
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

document.getElementById("captureBtn").addEventListener("click", async () => {
  setStatus("Считываю выделение...");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    setStatus("Не удалось определить активную вкладку.");
    return;
  }
  chrome.tabs.sendMessage(tab.id, { type: "READ_SELECTION" }, async (response) => {
    if (chrome.runtime.lastError) {
      setStatus("❌ Открой страницу instagram.com или threads.com и попробуй снова.");
      return;
    }
    if (!response || response.error) {
      setStatus(response?.error || "Ничего не найдено.");
      return;
    }
    const res = await chrome.runtime.sendMessage({
      type: "ADD_USERNAMES",
      usernames: response.usernames,
      platform: response.platform,
    });
    const skipped = response.usernames.length - res.added;
    setStatus(
      `✅ Добавлено: ${res.added}` + (skipped > 0 ? ` (уже было: ${skipped})` : "")
    );
    render();
  });
});

async function loadSendAsLink() {
  const { sendAsLink = false } = await chrome.storage.local.get("sendAsLink");
  document.getElementById("sendAsLink").checked = sendAsLink;
}

document.getElementById("sendAsLink").addEventListener("change", async (e) => {
  await chrome.storage.local.set({ sendAsLink: e.target.checked });
});

function updateStatusText(enabled) {
  document.getElementById("trackingStatusText").textContent = enabled
    ? "🟢 Активно — записывает профили"
    : "⏸ Остановлено";
}

async function loadTrackingState() {
  const { trackingEnabled = false } = await chrome.storage.local.get("trackingEnabled");
  document.getElementById("trackingToggle").checked = trackingEnabled;
  updateStatusText(trackingEnabled);
}

document.getElementById("trackingToggle").addEventListener("change", async (e) => {
  const enabled = e.target.checked;
  await chrome.storage.local.set({ trackingEnabled: enabled });
  updateStatusText(enabled);
});

render();
loadTrackingState();
loadSendAsLink();
