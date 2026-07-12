(function () {
  const RESERVED = new Set([
    "", "explore", "reels", "reel", "p", "stories", "direct", "accounts",
    "about", "developer", "legal", "privacy", "terms", "web", "tv",
    "topics", "locations", "tags", "session", "challenge", "emails",
    "api", "graphql", "oauth", "login", "signup", "settings",
    "notifications", "inbox", "ads", "lite", "creators", "nametag",
    "close_friends", "archive", "activity", "download", "language",
    "static", "logout", "hashtag", "guide", "guides",
  ]);
  const USERNAME_RE = /^[A-Za-z0-9._]{1,30}$/;
  let lastUsername = null;

  function extractUsername(pathname) {
    const parts = pathname.split("/").filter(Boolean);
    if (parts.length !== 1) return null;
    const candidate = parts[0];
    if (RESERVED.has(candidate.toLowerCase())) return null;
    if (!USERNAME_RE.test(candidate)) return null;
    return candidate;
  }

  function check() {
    const username = extractUsername(location.pathname);
    if (username && username !== lastUsername) {
      lastUsername = username;
      console.log(`%c[IG Tracker] Профиль: @${username}`, "color:#2563EB;font-weight:bold");
    } else if (!username) {
      lastUsername = null;
    }
  }

  // Instagram — SPA, при переходе между профилями обычной перезагрузки
  // страницы не происходит. Перехватываем pushState/replaceState и popstate,
  // чтобы ловить смену URL внутри приложения.
  const origPushState = history.pushState;
  const origReplaceState = history.replaceState;
  history.pushState = function (...args) {
    origPushState.apply(this, args);
    check();
  };
  history.replaceState = function (...args) {
    origReplaceState.apply(this, args);
    check();
  };
  window.addEventListener("popstate", check);

  check();
})();
