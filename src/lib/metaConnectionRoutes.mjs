import { isVerifiedConnection } from "./connectionSelection.mjs";

const DIRECT = "meta-ads-direct";
const PIPEBOARD = "meta-ads-mcp";

export function isMetaConnection(tool) {
  return tool?.canonical_provider === "meta-ads" || tool?.canonicalProvider === "meta-ads"
    || [DIRECT, PIPEBOARD].includes(tool?.slug || tool?.provider)
    || (tool?.name || tool?.display_name) === "Meta Ads";
}

function savedRoute(tool) {
  if (tool.slug === DIRECT) return DIRECT;
  if (tool.slug === PIPEBOARD
    || String(tool.base_url || "").replace(/\/$/, "") === "https://meta-ads.mcp.pipeboard.co") return PIPEBOARD;
  return tool.slug;
}

export function connectionIsReady(tool) {
  return Boolean(tool?.enabled && isVerifiedConnection(tool));
}

// The planner keeps its canonical Meta Ads entry. Only the connection UI expands
// it: one provider's saved grant must never hide another provider's Connect action.
export function metaConnectionRows(entries, savedTools, { includeSaved = false } = {}) {
  const saved = savedTools.filter(isMetaConnection);
  const source = includeSaved && saved.length && !entries.some(isMetaConnection)
    ? [...entries, { name: "Meta Ads", canonicalProvider: "meta-ads", icon: "🔗", routes: [] }]
    : entries;
  return source.flatMap((entry) => {
    if (!isMetaConnection(entry)) return [entry];
    const routes = new Map((entry.routes || [entry]).map((route) => [route.provider, route]));
    for (const tool of saved) {
      const provider = savedRoute(tool);
      if (!routes.has(provider)) routes.set(provider, { provider, connectable: false });
    }
    return [...routes.values()].flatMap((route) => {
      const matches = saved.filter((tool) => savedRoute(tool) === route.provider);
      const label = route.provider === DIRECT ? "Direct"
        : route.provider === PIPEBOARD ? "Pipeboard" : "Other connection";
      return (matches.length ? matches : [null]).map((connection) => {
        const isConnected = connectionIsReady(connection);
        const status = isConnected ? "Connected" : connection?.enabled === false ? "Disabled" : "Check connection";
        const account = connection?.external_account_id || (matches.length > 1 ? connection?.id : "");
        return {
          ...entry, ...route,
          name: entry.name,
          displayName: `Meta Ads — ${label}`,
          rowKey: connection ? `connection:${connection.id}` : `route:${route.provider}`,
          provider: connection?.slug || route.provider,
          connectionId: connection?.id,
          connection,
          isConnected,
          requestable: false,
          desc: connection ? `${status}${account ? ` · ${account}` : ""}`
            : route.provider === DIRECT ? "Sign in directly with Meta · Read-only reporting"
              : route.provider === PIPEBOARD ? "Sign in through Pipeboard · Read-only reporting" : "Separate authorization",
        };
      });
    });
  });
}
