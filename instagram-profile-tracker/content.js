// Ссылка на профиль в разметке Instagram выглядит как href="/username/" —
// это единственное надёжное отличие ника от отображаемого имени рядом с ним
// (имя — обычный текст, не ссылка).
const USERNAME_HREF_RE = /^\/([A-Za-z0-9._]{1,30})\/?$/;

function usernameFromHref(href) {
  if (!href) return null;
  const match = href.match(USERNAME_HREF_RE);
  return match ? match[1] : null;
}

function extractUsernamesFromSelection() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return { usernames: [], error: "Ничего не выделено на странице." };
  }

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

  if (usernames.size === 0) {
    return { usernames: [], error: "В выделении не найдено ссылок на профили." };
  }
  return { usernames: Array.from(usernames), error: null };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "READ_SELECTION") {
    sendResponse(extractUsernamesFromSelection());
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

  chrome.runtime.sendMessage({ type: "ADD_USERNAMES", usernames: result.usernames }, (res) => {
    const added = res?.added || 0;
    const skipped = result.usernames.length - added;
    showToast(`✅ Добавлено: ${added}` + (skipped > 0 ? ` (уже было: ${skipped})` : ""));
  });
});
