// Пути в instagram.com, которые не являются именами пользователей.
const RESERVED = new Set([
  "", "explore", "reels", "reel", "p", "stories", "direct", "accounts",
  "about", "developer", "legal", "privacy", "terms", "web", "tv",
  "topics", "locations", "tags", "session", "challenge", "emails",
  "api", "graphql", "oauth", "login", "signup", "settings",
  "notifications", "inbox", "ads", "lite", "creators", "nametag",
  "close_friends", "archive", "activity", "download", "language",
  "static", "logout", "hashtag", "guide", "guides"
]);

const USERNAME_RE = /^[A-Za-z0-9._]{1,30}$/;

//Usernames уже обработанные в текущем сеансе воркера — защита от гонки
// между onHistoryStateUpdated и onCompleted, стреляющими почти одновременно.
const processed = new Set();

function extractUsername(urlStr) {
  let u;
  try {
    u = new URL(urlStr);
  } catch {
    return null;
  }
  if (!u.hostname.endsWith("instagram.com")) return null;

  const parts = u.pathname.split("/").filter(Boolean);
  if (parts.length !== 1) return null;

  const candidate = parts[0];
  if (RESERVED.has(candidate.toLowerCase())) return null;
  if (!USERNAME_RE.test(candidate)) return null;
  return candidate;
}

function updateBadge(count) {
  chrome.action.setBadgeText({ text: count > 0 ? String(count) : "" });
  chrome.action.setBadgeBackgroundColor({ color: "#2563EB" });
}

async function addUsername(username) {
  const key = username.toLowerCase();
  if (processed.has(key)) return;
  processed.add(key);

  const { profiles = [] } = await chrome.storage.local.get("profiles");
  if (profiles.some((p) => p.username.toLowerCase() === key)) return;

  profiles.push({ username, addedAt: Date.now() });
  await chrome.storage.local.set({ profiles });
  updateBadge(profiles.length);

  const { autoSend } = await chrome.storage.local.get("autoSend");
  if (autoSend) {
    try {
      await sendToTelegram([username]);
    } catch (e) {
      console.warn("Instagram Profile Tracker: авто-отправка не удалась:", e.message);
    }
  }
}

function handleNavigation(details) {
  if (details.frameId !== 0) return;
  const username = extractUsername(details.url);
  if (username) addUsername(username);
}

chrome.webNavigation.onHistoryStateUpdated.addListener(handleNavigation, {
  url: [{ hostSuffix: "instagram.com" }],
});
chrome.webNavigation.onCompleted.addListener(handleNavigation, {
  url: [{ hostSuffix: "instagram.com" }],
});

chrome.runtime.onInstalled.addListener(async () => {
  const { profiles = [] } = await chrome.storage.local.get("profiles");
  updateBadge(profiles.length);
});

async function sendToTelegram(usernames) {
  const { botToken, chatId } = await chrome.storage.local.get(["botToken", "chatId"]);
  if (!botToken || !chatId) {
    throw new Error("Бот не настроен. Открой настройки расширения и укажи Bot Token и Chat ID.");
  }

  const list = usernames.map((u) => `@${u}`).join("\n");
  const text = `📋 Instagram-профили (${usernames.length}):\n${list}`;

  const resp = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
  const data = await resp.json();
  if (!data.ok) throw new Error(data.description || "Ошибка Telegram API");
  return data;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "SEND_TO_TELEGRAM") {
    sendToTelegram(msg.usernames)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }
  if (msg.type === "CLEAR_PROFILES") {
    chrome.storage.local.set({ profiles: [] }).then(() => {
      updateBadge(0);
      sendResponse({ ok: true });
    });
    return true;
  }
});
