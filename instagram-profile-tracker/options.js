async function load() {
  const { botToken = "", chatId = "" } = await chrome.storage.local.get(["botToken", "chatId"]);
  document.getElementById("botToken").value = botToken;
  document.getElementById("chatId").value = chatId;
  await refreshSeenCount();
}

async function refreshSeenCount() {
  const res = await chrome.runtime.sendMessage({ type: "GET_SEEN_COUNT" });
  document.getElementById("seenCount").textContent = res?.count ?? 0;
}

document.getElementById("clearSeenBtn").addEventListener("click", async () => {
  if (!confirm("Очистить всю базу уже виденных ников? В следующий раз все ники будут считаны заново как новые.")) {
    return;
  }
  await chrome.runtime.sendMessage({ type: "CLEAR_SEEN" });
  await refreshSeenCount();
});

document.getElementById("saveBtn").addEventListener("click", async () => {
  const botToken = document.getElementById("botToken").value.trim();
  const chatId = document.getElementById("chatId").value.trim();

  await chrome.storage.local.set({ botToken, chatId });

  const status = document.getElementById("status");
  status.textContent = "✅ Сохранено";
  setTimeout(() => (status.textContent = ""), 2000);
});

load();
