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
