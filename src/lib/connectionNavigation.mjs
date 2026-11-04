const RETURN_KEY = "aura_same_tab_authorization";
const RETURN_LIFETIME_MS = 30 * 60 * 1000;

// Starting another connection or consuming a return must not keep a previous
// Meta Ads deep link alive. Leave workflow, workspace and unrelated URL state alone.
export function clearAuthorizationNavigation(browser = window) {
  try { browser.sessionStorage.removeItem(RETURN_KEY); } catch { /* Optional storage. */ }
  try {
    const url = new URL(browser.location.href);
    const keys = ["connect", "oauth_provider", "oauth_status", "oauth_message", "tool_connected"];
    if (!keys.some((key) => url.searchParams.has(key))) return;
    for (const key of keys) url.searchParams.delete(key);
    browser.history.replaceState(browser.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  } catch { /* Optional navigation cleanup must not interrupt authorization. */ }
}

function hasSameOriginOpener(browser) {
  try {
    return Boolean(browser.opener && browser.opener.location.origin === browser.location.origin);
  } catch {
    return false;
  }
}

export function usesSameTabAuthorization(provider, connection = null) {
  return provider === "meta-ads-mcp" || provider === "meta-ads"
    || /^agent-meta-ads-[a-f0-9]{10}$/.test(provider || "")
    || connection?.canonical_provider === "meta-ads";
}

// Only a broker response can supply the destination. Never take an OAuth URL,
// workspace, code, or state from a connection-screen link.
export function redirectConnectorAuthorization(session, browser = window) {
  const destination = new URL(session.authorization_url);
  if (!["native", "zernio"].includes(session.backend) || destination.protocol !== "https:"
    || destination.username || destination.password) {
    throw new Error("AURA could not prepare a secure authorization page.");
  }
  try {
    browser.sessionStorage.setItem(RETURN_KEY, JSON.stringify({
      provider: session.provider,
      startedAt: Date.now(),
    }));
  } catch { /* Consent still works when optional session storage is disabled. */ }
  browser.location.assign(destination.href);
  return { redirecting: true, connected: false };
}

export function isSameTabAuthorizationReturn(search, browser = window) {
  const params = new URLSearchParams(search);
  const provider = params.get("oauth_provider");
  if (!["success", "error"].includes(params.get("oauth_status"))) return false;
  try {
    const pending = JSON.parse(browser.sessionStorage.getItem(RETURN_KEY));
    const age = Date.now() - pending?.startedAt;
    if (usesSameTabAuthorization(pending?.provider) && age >= 0 && age < RETURN_LIFETIME_MS
      && (provider === pending.provider
        || (provider === "mcp-agent" && params.get("oauth_status") === "error"))) return true;
  } catch { /* A missing marker must not prevent the connection screen opening. */ }
  // With storage disabled, a normal tab (including one opened from chat) has
  // no AURA opener to notify or close.
  return !hasSameOriginOpener(browser) && usesSameTabAuthorization(provider);
}

export function connectionScreenPreset(search, browser = window) {
  const params = new URLSearchParams(search);
  const returned = isSameTabAuthorizationReturn(search, browser);
  // An explicit return for another app overrides a leftover Meta Ads link.
  if ((params.has("oauth_provider") || params.has("tool_connected")) && !returned) return null;
  if (params.get("connect") !== "meta-ads" && !returned) return null;
  return {
    query: "Meta Ads",
    // URL parameters describe navigation only. Connected status always comes
    // from the authenticated connection service after the callback.
    message: returned
      ? params.get("oauth_status") === "error"
        ? "Meta Ads authorization did not finish. Tap Connect to try again."
        : "Meta Ads authorization returned. Check your verified connection status below."
      : "Connect Meta Ads via Pipeboard. Sign-in opens in this tab and returns to AURA.",
  };
}

export function shouldNotifyAuthorizationOpener(search, browser = window) {
  if (isSameTabAuthorizationReturn(search, browser)) return false;
  // A link opened from chat is not an AURA consent popup.
  return hasSameOriginOpener(browser);
}
