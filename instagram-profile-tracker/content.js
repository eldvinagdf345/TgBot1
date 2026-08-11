// Ссылка на профиль в разметке Instagram выглядит как href="/username/",
// а в Threads — как href="/@username" (с "@" в пути). Это самый надёжный
// способ отличить ник от отображаемого имени рядом — но в некоторых списках
// (например "Отметки Нравится") сайт рисует строки без <a>, просто текстом
// с обработчиком клика. Поэтому это лишь первая попытка, а не единственная.
const USERNAME_HREF_RE = /^\/([A-Za-z0-9._]{1,30})\/?$/;
const THREADS_HREF_RE = /^\/@([A-Za-z0-9._]{1,30})\/?$/;
// Ники в обеих сетях — только латиница, цифры, точка и подчёркивание, без
// пробелов (в Threads ещё и видимый текст на странице часто идёт с "@"
// впереди). Отображаемое имя почти всегда содержит пробел, кириллицу или
// эмодзи, поэтому по этому шаблону их можно различить в чистом тексте.
const USERNAME_LINE_RE = /^@?[A-Za-z0-9._]{1,30}$/;
const STOPWORDS = new Set([
  "follow", "following", "requested", "remove", "message", "unfollow",
  "reply", "repost", "quote", "share", "like", "likes",
  "подписаться", "отписаться", "подписки", "запрошено", "написать",
  "удалить", "заблокировать", "block", "ok", "cancel", "отмена",
  "ответить", "поделиться", "цитировать", "репост", "нравится",
]);

function isThreadsSite() {
  return location.hostname.includes("threads.");
}

function usernameFromHref(href) {
  if (!href) return null;
  let match = href.match(THREADS_HREF_RE);
  if (match) return match[1];
  match = href.match(USERNAME_HREF_RE);
  return match ? match[1] : null;
}

function extractLinksFromSelection(selection) {
  const usernames = new Set();
  for (let i = 0; i < selection.rangeCount; i++) {
    const range = selection.getRangeAt(i);

    const fragment = range.cloneContents();
    fragment.querySelectorAll("a[href]").forEach((a) => {
      const username = usernameFromHref(a.getAttribute("href"));
      if (username) usernames.add(username);
    });

    // На случай, если выделение начинается/заканчивается внутри самой
    // ссылки и cloneContents() не захватывает элемент целиком.
    let node = range.commonAncestorContainer;
    if (node.nodeType === Node.TEXT_NODE) node = node.parentElement;
    const enclosingLink = node && node.closest ? node.closest("a[href]") : null;
    if (enclosingLink) {
      const username = usernameFromHref(enclosingLink.getAttribute("href"));
      if (username) usernames.add(username);
    }
  }
  return usernames;
}

function relativeLuminance(r, g, b) {
  const srgb = [r, g, b].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * srgb[0] + 0.7152 * srgb[1] + 0.0722 * srgb[2];
}

// Сайт красит ник почти белым (главный текст), а имя под ним —
// приглушённым серым и/или с пониженной прозрачностью (второстепенный
// текст). Charset у имени вроде "DS" может случайно совпасть с шаблоном
// ника, поэтому дополнительно смотрим на реальный цвет текста в DOM.
function isMutedText(el) {
  const style = getComputedStyle(el);
  const match = style.color.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
  if (!match) return false;
  const r = Number(match[1]);
  const g = Number(match[2]);
  const b = Number(match[3]);
  const a = match[4] === undefined ? 1 : Number(match[4]);
  const luminance = relativeLuminance(r, g, b) * a;
  const opacity = parseFloat(style.opacity);
  return luminance < 0.45 || (!Number.isNaN(opacity) && opacity < 0.75);
}

function extractFromTextNodes(selection) {
  const usernames = new Set();

  for (let i = 0; i < selection.rangeCount; i++) {
    const range = selection.getRangeAt(i);
    let root = range.commonAncestorContainer;
    if (root.nodeType === Node.TEXT_NODE) root = root.parentElement;
    if (!root) continue;

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.textContent.trim()) return NodeFilter.FILTER_REJECT;
        return selection.containsNode(node, true)
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    });

    let node;
    while ((node = walker.nextNode())) {
      const text = node.textContent.trim();
      if (!USERNAME_LINE_RE.test(text)) continue;
      if (STOPWORDS.has(text.toLowerCase().replace(/^@/, ""))) continue;
      const el = node.parentElement;
      if (el && isMutedText(el)) continue; // похоже на имя, а не на ник
      usernames.add(text.replace(/^@/, ""));
    }
  }
  return usernames;
}

function extractUsernamesFromSelection() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return { usernames: [], error: "Ничего не выделено на странице." };
  }

  let usernames = extractLinksFromSelection(selection);
  if (usernames.size === 0) {
    usernames = extractFromTextNodes(selection);
  }

  if (usernames.size === 0) {
    return { usernames: [], error: "Не удалось распознать ники в выделении." };
  }
  return { usernames: Array.from(usernames), error: null };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "READ_SELECTION") {
    const result = extractUsernamesFromSelection();
    sendResponse({ ...result, platform: isThreadsSite() ? "threads" : "instagram" });
  }
});

// Горячая клавиша: выделил список профилей на странице → нажал L → ники
// добавлены, без похода в попап расширения.
let toastEl = null;
function showToast(text, isError) {
  if (!toastEl) {
    toastEl = document.createElement("div");
    toastEl.style.cssText = [
      "position:fixed", "bottom:24px", "right:24px", "z-index:2147483647",
      "background:#111827", "border:1px solid #1F2937", "border-radius:8px",
      "padding:10px 14px", "font:13px 'Segoe UI',sans-serif",
      "box-shadow:0 4px 16px rgba(0,0,0,.4)", "transition:opacity .2s",
      "pointer-events:none",
    ].join(";");
    document.body.appendChild(toastEl);
  }
  toastEl.style.color = isError ? "#EF4444" : "#F1F5F9";
  toastEl.textContent = text;
  toastEl.style.opacity = "1";
  clearTimeout(toastEl._hideTimer);
  toastEl._hideTimer = setTimeout(() => {
    toastEl.style.opacity = "0";
  }, 2200);
}

document.addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "l") return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;

  const active = document.activeElement;
  const isEditable =
    active &&
    (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable);
  if (isEditable) return;

  const result = extractUsernamesFromSelection();
  if (result.error) {
    showToast(result.error, true);
    return;
  }

  chrome.runtime.sendMessage(
    { type: "ADD_USERNAMES", usernames: result.usernames, platform: isThreadsSite() ? "threads" : "instagram" },
    (res) => {
      const added = res?.added || 0;
      const skipped = result.usernames.length - added;
      showToast(`✅ Добавлено: ${added}` + (skipped > 0 ? ` (уже было: ${skipped})` : ""));
    }
  );
});
