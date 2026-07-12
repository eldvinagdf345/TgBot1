async function load() {
  const { botToken = "", chatId = "", autoSend = false } = await chrome.storage.local.get([
    "botToken",
    "chatId",
    "autoSend",
  ]);
  document.getElementById("botToken").value = botToken;
  document.getElementById("chatId").value = chatId;
  document.getElementById("autoSend").checked = autoSend;
}

document.getElementById("saveBtn").addEventListener("click", async () => {
  const botToken = document.getElementById("botToken").value.trim();
  const chatId = document.getElementById("chatId").value.trim();
  const autoSend = document.getElementById("autoSend").checked;

  await chrome.storage.local.set({ botToken, chatId, autoSend });

  const status = document.getElementById("status");
  status.textContent = "✅ Сохранено";
  setTimeout(() => (status.textContent = ""), 2000);
});

load();
