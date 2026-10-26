const RETURN_KEY = "aura_same_tab_authorization";
const RETURN_LIFETIME_MS = 30 * 60 * 1000;

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
  if (session.backend !== "native" || destination.protocol !== "https:"
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
      && (provider === pending.provider || provider === "mcp-agent")) return true;
  } catch { /* A missing marker must not prevent the connection screen opening. */ }
  // With storage disabled, a normal tab (including one opened from chat) has
  // no AURA opener to notify or close.
  return !hasSameOriginOpener(browser) && usesSameTabAuthorization(provider);
}

export function connectionScreenPreset(search, browser = window) {
  const params = new URLSearchParams(search);
  const returned = isSameTabAuthorizationReturn(search, browser);
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
