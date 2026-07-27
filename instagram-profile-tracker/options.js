async function load() {
  const { botToken = "", chatId = "" } = await chrome.storage.local.get(["botToken", "chatId"]);
  document.getElementById("botToken").value = botToken;
  document.getElementById("chatId").value = chatId;
}

document.getElementById("saveBtn").addEventListener("click", async () => {
  const botToken = document.getElementById("botToken").value.trim();
  const chatId = document.getElementById("chatId").value.trim();

  await chrome.storage.local.set({ botToken, chatId });

  const status = document.getElementById("status");
  status.textContent = "✅ Сохранено";
  setTimeout(() => (status.textContent = ""), 2000);
});

load();
