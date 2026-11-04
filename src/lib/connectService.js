import { replaceConnections } from "@/lib/connectionsStore";
import { isVerifiedConnection, matchingConnections, selectConnection } from "@/lib/connectionSelection.mjs";
import { clearAuthorizationNavigation, usesSameTabAuthorization } from "@/lib/connectionNavigation.mjs";
import { googleAdsAccountDialog } from "@/lib/googleAdsAccountDialog";
import {
  authorizeConnectorBroker,
  disconnectPythonConnection,
  getManagedConnectorStatus,
  listPythonTools,
  listGoogleAdsAccounts,
  pythonRuntimeEnabled,
  reserveAuthorizationWindow,
  searchConnectorBrokerApps,
  selectGoogleAdsAccount,
  testPythonConnection,
} from "@/lib/auraApi";
import {
  CATALOG,
  catalogEntryFor,
  ensurePlanConnectionRoute,
  providerForTool,
  replaceToolCatalog,
} from "@/lib/toolCatalog";

const HYDRATION_TTL_MS = 30_000;
let hydrationPromise = null;
let hydratedTools = null;
let hydratedAt = 0;

export async function chooseGoogleAdsAccount(tool, { force = false } = {}) {
  if (tool?.slug !== "google-ads" || tool.connection_backend !== "pipedream"
    || (!force && tool.google_ads_account)) return tool;
  const selected = await googleAdsAccountDialog({
    selected: tool.google_ads_account,
    load: (login, search) => listGoogleAdsAccounts(tool.id, login, search),
    save: (selection) => selectGoogleAdsAccount(tool.id, selection),
  });
  return selected ? { ...tool, google_ads_account: selected } : tool;
}

export async function connectTool(toolName, opts = {}) {
  if (!pythonRuntimeEnabled) {
    throw new Error("AURA's secure connection service is not available right now.");
  }
  clearAuthorizationNavigation();
  const requestedProvider = String(opts.provider || "").trim().toLowerCase();
  // Reserve a native consent window in the click's user gesture, before any
  // catalog/account request. Otherwise Safari can silently block Update access.
  let authorizationWindow = null;
  try {
    const knownEntry = catalogEntryFor(toolName);
    const knownRoute = knownEntry?.routes?.find((route) => route.provider === requestedProvider);
    const knownAccount = opts.connectionId
      ? hydratedTools?.find((tool) => tool.id === opts.connectionId) : null;
    const knownProvider = knownAccount?.slug || requestedProvider || knownEntry?.provider;
    const knownBackend = knownAccount?.connection_backend || knownRoute?.connectionBackend || knownEntry?.connectionBackend;
    if (knownEntry?.connectable && knownProvider && !usesSameTabAuthorization(knownProvider, knownAccount)
      && !["pipedream", "wordpress_plugin", "shopify_client_credentials"].includes(knownBackend)) {
      authorizationWindow = reserveAuthorizationWindow(knownProvider);
    }
    const entry = await ensurePlanConnectionRoute(toolName, requestedProvider, searchConnectorBrokerApps);
    if (!entry?.connectable || !entry.provider) {
      throw new Error(`${toolName} is not available as a verified one-click connector yet. ` +
        "Your work remains saved and no API key or MCP setup is required from you.");
    }
    const requestedRoute = entry.routes?.find(
      (route) => route.provider === requestedProvider && route.connectable
    );
    if (requestedProvider && !requestedRoute) {
      throw new Error(`${toolName} needs its exact plan connection. This connector route is not available for one-click access yet.`);
    }
    const provider = requestedRoute?.provider || entry.provider;
    const existing = await getToolConnection(toolName, opts.connectionId, provider, {
      // A fresh Connect action must keep the preferred provider shown on the
      // card. A broad Google Workspace entry is not a Google Sheets account
      // on that route. Explicit reconnects still retain their chosen account.
      exactProvider: Boolean(requestedProvider || (!opts.connectionId && entry.preferredConnection)),
    });
    const authorizationProvider = existing?.slug || provider;
    const backend = existing?.connection_backend || requestedRoute?.connectionBackend || entry.connectionBackend;
    const sameTab = usesSameTabAuthorization(authorizationProvider, existing);
    if (!authorizationWindow && !sameTab && !["pipedream", "wordpress_plugin", "shopify_client_credentials"].includes(backend)) authorizationWindow = reserveAuthorizationWindow(authorizationProvider);
    const result = await authorizeConnectorBroker(authorizationProvider, {
      connection: existing,
      timeoutMs: 600000,
      reservedWindow: authorizationWindow,
      sameTab,
    });

    if (result.redirecting) {
      return { method: "oauth", connected: false, authorizationStarted: true, provider: authorizationProvider };
    }
    if (!result.tool?.id) throw new Error(`${toolName} access could not be verified.`);
    const verification = await testPythonConnection(result.tool.id);
    if (!isVerifiedConnection(verification)) {
      throw new Error(`AURA is still restoring ${toolName} access. Your work is preserved.`);
    }
    const refreshedTools = await hydrateConnections({ force: true });
    const connection = await chooseGoogleAdsAccount(
      refreshedTools.find((tool) => tool.id === result.tool.id) || result.tool,
    );
    return {
      method: result.managed ? "managed" : "oauth",
      connected: true,
      provider: authorizationProvider,
      connection,
    };
  } catch (error) {
    if (authorizationWindow && !authorizationWindow.closed) authorizationWindow.close();
    throw error;
  }
}
export async function hydrateConnections({ force = false } = {}) {
  if (!pythonRuntimeEnabled) {
    throw new Error("AURA's secure connection service is not configured.");
  }
  if (!force && hydratedTools && Date.now() - hydratedAt < HYDRATION_TTL_MS) {
    return hydratedTools;
  }
  if (hydrationPromise) {
    if (!force) return hydrationPromise;
    // Consent can finish while a background check still holds the old tool
    // snapshot. Wait for it, then read again before checking the new grant.
    await hydrationPromise.catch(() => null);
    // Concurrent forced callers can share a refresh begun after that check.
    if (hydrationPromise) return hydrationPromise;
  }

  hydrationPromise = (async () => {
    const status = await getManagedConnectorStatus(force).catch(() => null);
    if (status) replaceToolCatalog(status);

    const tools = await listPythonTools();
    const health = await Promise.all(tools.map(async (tool) => {
      if (!tool.enabled || (tool.kind !== "oauth" && !["wordpress_plugin", "shopify_client_credentials"].includes(tool.connection_backend))) return { tool, connected: Boolean(tool.enabled) };
      try {
        const result = await testPythonConnection(tool.id);
        return { tool, connected: isVerifiedConnection(result) };
      } catch {
        return { tool, connected: false };
      }
    }));

    const map = {};
    for (const { tool, connected } of health) {
      if (!connected) continue;
      if (tool.display_name) map[tool.display_name] = true;
      CATALOG.filter((entry) => matchingConnections([tool], entry.name, entry.provider).length).forEach((entry) => {
        map[entry.name] = true;
      });
    }
    replaceConnections(map);
    hydratedTools = tools;
    hydratedAt = Date.now();
    return tools;
  })().finally(() => {
    hydrationPromise = null;
  });
  return hydrationPromise;
}

export async function getToolConnection(toolName, connectionId = null, providerOverride = null, options = {}) {
  const tools = await listPythonTools();
  return selectConnection(tools, {
    toolName,
    provider: providerOverride || providerForTool(toolName),
    connectionId,
    exactProvider: Boolean(options.exactProvider),
  });
}

export async function testToolConnection(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Connection testing requires the secure control plane.");
  const tool = await getToolConnection(toolName, connectionId);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  return testPythonConnection(tool.id);
}

export async function disconnectTool(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Revoking connections requires the secure control plane.");
  const tool = await getToolConnection(toolName, connectionId);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  await disconnectPythonConnection(tool.id);
  await hydrateConnections({ force: true });
  return { disconnected: true };
}

export async function reconnectTool(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Reauthorization requires the secure control plane.");
  clearAuthorizationNavigation();
  let authorizationWindow = null;
  try {
    const tool = await getToolConnection(toolName, connectionId);
    if (!tool) throw new Error(`${toolName} is not connected.`);
    // Existing connections remain reconnectable even when their provider is
    // absent from the current one-click marketplace catalog.
    const provider = tool.slug || providerForTool(toolName);
    if (!provider) throw new Error(`${toolName} has no reconnectable provider.`);
    const sameTab = usesSameTabAuthorization(provider, tool);
    if (!sameTab && !["pipedream", "shopify_client_credentials"].includes(tool.connection_backend)) {
      authorizationWindow = reserveAuthorizationWindow(provider, true);
    }
    const result = await authorizeConnectorBroker(provider, {
      connection: tool,
      // Google account selection and consent can take longer than two minutes.
      timeoutMs: 600000,
      reservedWindow: authorizationWindow,
      sameTab,
    });
    if (result.redirecting) return result;
    await hydrateConnections({ force: true });
    result.tool = await chooseGoogleAdsAccount(result.tool);
    return result;
  } catch (error) {
    if (authorizationWindow && !authorizationWindow.closed) authorizationWindow.close();
    throw error;
  }
}
