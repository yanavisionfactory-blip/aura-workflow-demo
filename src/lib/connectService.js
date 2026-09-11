import { base44 } from "@/api/base44Client";
import { setConnection, replaceConnections } from "@/lib/connectionsStore";
import { isVerifiedConnection, selectConnection } from "@/lib/connectionSelection.mjs";
import { isManagedOAuthTool, managedOAuthProviderFor } from "@/lib/connectionPolicy.mjs";
import {
  addPythonTool,
  authorizeManagedConnector,
  authorizeCustomOAuth,
  authorizeOAuth,
  discoverPythonConnector,
  disconnectPythonConnection,
  getManagedConnectorStatus,
  listPythonTools,
  pythonRuntimeEnabled,
  reconnectPythonConnection,
  reserveAuthorizationWindow,
  testPythonConnection,
} from "@/lib/auraApi";

const CONNECTION_NAMES = {
  atlassian: ["Jira"],
  jira: ["Jira"],
  google: ["Gmail", "Google Drive", "Google Calendar", "Google Sheets"],
  "google-workspace": ["Gmail", "Google Drive", "Google Calendar", "Google Sheets"],
  notion: ["Notion"],
  slack: ["Slack"],
  airtable: ["Airtable"],
  tiktok: ["TikTok"],
  mailchimp: ["Mailchimp"],
  canva: ["Canva"],
  hubspot: ["HubSpot"],
};
const connectionAliases = (tool) => {
  const identity = `${tool.slug || ""} ${tool.display_name || ""}`.toLowerCase();
  if (identity.includes("atlassian") || identity.includes("jira")) return ["Jira"];
  if (identity.includes("google")) return CONNECTION_NAMES.google;
  if (identity.includes("notion")) return ["Notion"];
  return CONNECTION_NAMES[String(tool.slug || "").toLowerCase()] || [];
};
const slugify = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const credentialsFor = (opts) => opts.credentials || (opts.apiKey ? { api_key: opts.apiKey } : {});

export function hasStandardOAuth(toolName) {
  return isManagedOAuthTool(toolName);
}

export async function connectTool(toolName, opts = {}) {
  if (pythonRuntimeEnabled) {
    const provider = managedOAuthProviderFor(toolName);
    if (provider) {
      // Reserve the provider window while the click still has browser user
      // activation. Backend discovery happens afterwards and cannot turn this
      // into a blocked or unrelated frontend configuration dialog.
      const authorizationWindow = reserveAuthorizationWindow(provider);
      let result;
      try {
        const existing = await getToolConnection(toolName, opts.connectionId);
        const managed = await getManagedConnectorStatus().catch(() => ({ configured: false, providers: [] }));
        result = existing?.kind === "oauth"
          ? await reconnectPythonConnection(existing, 120000, authorizationWindow)
          : managed.configured && managed.providers.includes(provider)
            ? await authorizeManagedConnector(provider, 120000, authorizationWindow)
            : await authorizeOAuth(provider, 120000, authorizationWindow);
      } catch (error) {
        if (!authorizationWindow.closed) authorizationWindow.close();
        throw error;
      }
      if (result.redirecting) return { method: "oauth", connected: false, authorizationStarted: true, provider };
      if (!result.tool?.id) throw new Error(`${toolName} access could not be verified.`);
      const verification = await testPythonConnection(result.tool.id);
      if (!isVerifiedConnection(verification)) {
        throw new Error(`AURA is still restoring ${toolName} access. Your work is preserved.`);
      }
      await hydrateConnections();
      return {
        method: result.managed ? "managed" : "oauth",
        connected: true,
        provider,
        connection: result.tool,
      };
    }

    if (opts.administrativeSetup !== true) {
      throw new Error(
        `${toolName} is not available as a one-click AURA connection yet. ` +
        "No API key or MCP setup is required from you, and your work remains saved."
      );
    }

    if (opts.connectionKind === "oauth2") {
      const result = await authorizeCustomOAuth({
        slug: slugify(toolName),
        display_name: toolName,
        authorization_url: opts.authorizationUrl,
        token_url: opts.tokenUrl,
        api_base_url: opts.baseUrl,
        client_id: opts.clientId,
        client_secret: opts.clientSecret || "",
        scopes: opts.scopes || [],
        authorization_params: opts.authorizationParams || {},
        token_params: opts.tokenParams || {},
        token_auth_method: opts.tokenAuthMethod || (opts.clientSecret ? "client_secret_post" : "none"),
        capabilities: opts.capabilities || [{
          name: "api.request",
          description: "Call the connected application's API",
          permission_scope: "write",
          requires_approval: true,
          transport: { method: "POST", path: "" },
        }],
      });
      await hydrateConnections();
      return { method: "oauth2", connected: true, connection: result.tool };
    }

    if (!opts.baseUrl) {
      throw new Error("Administrative connector provisioning requires a backend-managed endpoint.");
    }
    const kind = opts.connectionKind || "openapi";
    const credentials = credentialsFor(opts);
    let connection;
    if (kind === "api_key") {
      connection = await addPythonTool({
        slug: slugify(toolName),
        displayName: toolName,
        kind,
        baseUrl: opts.baseUrl,
        credentials,
        allowedOperations: opts.allowedOperations || ["http.request"],
        config: opts.config || {},
      });
    } else {
      connection = await discoverPythonConnector({
        slug: slugify(toolName),
        displayName: toolName,
        kind,
        baseUrl: opts.baseUrl,
        credentials,
        config: { name: toolName, ...(opts.config || {}) },
      });
    }
    setConnection(toolName, true);
    return { method: kind, connected: true, connection };
  }

  const res = await base44.functions.invoke("resolveToolConnection", { tool: toolName });
  const info = res.data;
  if (info.method === "interface") return { method: info.method, interfaceTool: toolName, connected: false };
  if (info.method === "api_key" && !opts.apiKey) return { method: info.method, connected: false, needsApiKey: true };
  if (info.method === "oauth" && !info.oauthAuthorized) return { method: info.method, connected: false, needsAuthorization: true, connector: info.connector };
  await base44.functions.invoke("recordToolConnection", { tool: toolName, method: info.method, meta: opts });
  setConnection(toolName, true);
  return { method: info.method, connected: true };
}

export async function hydrateConnections() {
  if (pythonRuntimeEnabled) {
    const tools = await listPythonTools();
    const map = {};
    const health = await Promise.all(tools.map(async (tool) => {
      if (!tool.enabled || tool.kind !== "oauth") return { tool, connected: !!tool.enabled };
      try {
        const result = await testPythonConnection(tool.id);
        return { tool, connected: result.status === "verified" && result.verification?.ok !== false };
      } catch {
        return { tool, connected: false };
      }
    }));
    for (const { tool, connected } of health) {
      if (!tool.enabled) continue;
      if (!connected) continue;
      if (tool.display_name) map[tool.display_name] = true;
      const aliases = connectionAliases(tool);
      aliases.forEach((name) => { map[name] = true; });
      if (String(tool.display_name || "").toLowerCase() === "google workspace") {
        CONNECTION_NAMES.google.forEach((name) => { map[name] = true; });
      }
    }
    replaceConnections(map);
    return tools;
  }
  const res = await base44.functions.invoke("listToolConnections", {});
  replaceConnections(res.data?.connections || {});
  return [];
}

export async function getToolConnection(toolName, connectionId = null) {
  const tools = await listPythonTools();
  const provider = managedOAuthProviderFor(toolName);
  return selectConnection(tools, { toolName, provider, connectionId });
}

export async function testToolConnection(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Connection testing requires the Python control plane.");
  const tool = await getToolConnection(toolName, connectionId);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  return testPythonConnection(tool.id);
}

export async function disconnectTool(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Revoking connections requires the Python control plane.");
  const tool = await getToolConnection(toolName, connectionId);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  await disconnectPythonConnection(tool.id);
  await hydrateConnections();
  return { disconnected: true };
}

export async function reconnectTool(toolName, connectionId = null) {
  if (!pythonRuntimeEnabled) throw new Error("Reauthorization requires the Python control plane.");
  const provider = managedOAuthProviderFor(toolName);
  const authorizationWindow = reserveAuthorizationWindow(provider || slugify(toolName), true);
  try {
    const tool = await getToolConnection(toolName, connectionId);
    if (!tool) throw new Error(`${toolName} is not connected.`);
    const result = await reconnectPythonConnection(tool, 120000, authorizationWindow);
    await hydrateConnections();
    return result;
  } catch (error) {
    if (!authorizationWindow.closed) authorizationWindow.close();
    throw error;
  }
}

export async function recordInterfaceConnection(toolName, meta = {}) {
  if (pythonRuntimeEnabled) {
    if (!meta.baseUrl) throw new Error("Paste the tool URL before connecting it.");
    return connectTool(toolName, {
      administrativeSetup: true,
      baseUrl: meta.baseUrl,
      connectionKind: "browser",
      credentials: meta.credentials || {},
      config: meta,
    });
  }
  await base44.functions.invoke("recordToolConnection", { tool: toolName, method: "interface", meta });
  setConnection(toolName, true);
  return { connected: true };
}
