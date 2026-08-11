// Пути в instagram.com, которые не являются именами пользователей.
const RESERVED_IG = new Set([
  "", "explore", "reels", "reel", "p", "stories", "direct", "accounts",
  "about", "developer", "legal", "privacy", "terms", "web", "tv",
  "topics", "locations", "tags", "session", "challenge", "emails",
  "api", "graphql", "oauth", "login", "signup", "settings",
  "notifications", "inbox", "ads", "lite", "creators", "nametag",
  "close_friends", "archive", "activity", "download", "language",
  "static", "logout", "hashtag", "guide", "guides"
]);

const USERNAME_RE = /^[A-Za-z0-9._]{1,30}$/;

// Threads.com — профиль всегда с "@" в пути ("/@ник"), это само по себе
// отличает его от системных разделов сайта (/search, /activity и т.д.),
// поэтому отдельный список зарезервированных слов не нужен.
function detectPlatform(hostname) {
  if (hostname.endsWith("instagram.com")) return "instagram";
  if (hostname.endsWith("threads.com") || hostname.endsWith("threads.net")) return "threads";
  return null;
}

//Usernames уже обработанные в текущем сеансе воркера — защита от гонки
// между onHistoryStateUpdated и onCompleted, стреляющими почти одновременно.
const processed = new Set();

function extractProfile(urlStr) {
  let u;
  try {
    u = new URL(urlStr);
  } catch {
    return null;
  }

  const platform = detectPlatform(u.hostname);
  if (!platform) return null;

  const parts = u.pathname.split("/").filter(Boolean);
  if (parts.length !== 1) return null;

  if (platform === "threads") {
    if (!parts[0].startsWith("@")) return null;
    const candidate = parts[0].slice(1);
    if (!USERNAME_RE.test(candidate)) return null;
    return { username: candidate, platform };
  }

  const candidate = parts[0];
  if (RESERVED_IG.has(candidate.toLowerCase())) return null;
  if (!USERNAME_RE.test(candidate)) return null;
  return { username: candidate, platform };
}

function updateBadge(count) {
  chrome.action.setBadgeText({ text: count > 0 ? String(count) : "" });
  chrome.action.setBadgeBackgroundColor({ color: "#2563EB" });
}

async function addUsername(username, platform) {
  const key = username.toLowerCase();
  if (processed.has(key)) return;
  processed.add(key);

  const { profiles = [] } = await chrome.storage.local.get("profiles");
  if (profiles.some((p) => p.username.toLowerCase() === key)) return;

  profiles.push({ username, platform, addedAt: Date.now() });
  await chrome.storage.local.set({ profiles });
  updateBadge(profiles.length);
}

async function isTrackingEnabled() {
  const { trackingEnabled = false } = await chrome.storage.local.get("trackingEnabled");
  return trackingEnabled;
}

async function handleNavigation(details) {
  if (details.frameId !== 0) return;
  const profile = extractProfile(details.url);
  if (!profile) return;
  if (!(await isTrackingEnabled())) return;
  addUsername(profile.username, profile.platform);
}

const NAV_FILTER = {
  url: [{ hostSuffix: "instagram.com" }, { hostSuffix: "threads.com" }, { hostSuffix: "threads.net" }],
};

chrome.webNavigation.onHistoryStateUpdated.addListener(handleNavigation, NAV_FILTER);
chrome.webNavigation.onCompleted.addListener(handleNavigation, NAV_FILTER);

chrome.runtime.onInstalled.addListener(async () => {
  const { profiles = [] } = await chrome.storage.local.get("profiles");
  updateBadge(profiles.length);
});

function profileUrl(profile) {
  return profile.platform === "threads"
    ? `https://www.threads.com/@${profile.username}`
    : `https://www.instagram.com/${profile.username}/`;
}

async function sendToTelegram(profiles) {
  const { botToken, chatId, sendAsLink = false } = await chrome.storage.local.get([
    "botToken",
    "chatId",
    "sendAsLink",
  ]);
  if (!botToken || !chatId) {
    throw new Error("Бот не настроен. Открой настройки расширения и укажи Bot Token и Chat ID.");
  }

  const list = profiles
    .map((p) => (sendAsLink ? profileUrl(p) : `@${p.username}`))
    .join("\n");
  const text = `📋 Профили (${profiles.length}):\n${list}`;

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
    sendToTelegram(msg.profiles)
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
  if (msg.type === "ADD_USERNAMES") {
    (async () => {
      const platform = msg.platform === "threads" ? "threads" : "instagram";
      const { profiles = [] } = await chrome.storage.local.get("profiles");
      const existing = new Set(profiles.map((p) => p.username.toLowerCase()));
      let added = 0;
      for (const username of msg.usernames) {
        const key = username.toLowerCase();
        if (existing.has(key)) continue;
        existing.add(key);
        profiles.push({ username, platform, addedAt: Date.now() });
        added++;
      }
      if (added > 0) {
        await chrome.storage.local.set({ profiles });
        updateBadge(profiles.length);
      }
      sendResponse({ ok: true, added });
    })();
    return true;
  }
});
