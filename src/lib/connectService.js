import { base44 } from "@/api/base44Client";
import { setConnection, replaceConnections } from "@/lib/connectionsStore";
import {
  addPythonTool,
  authorizeCustomOAuth,
  authorizeOAuth,
  discoverPythonConnector,
  disconnectPythonConnection,
  listPythonTools,
  pythonRuntimeEnabled,
  reconnectPythonConnection,
  testPythonConnection,
} from "@/lib/auraApi";

const PYTHON_OAUTH = { Gmail: "google", "Google Drive": "google", "Google Calendar": "google", "Google Sheets": "google", Jira: "jira", Airtable: "airtable", Notion: "notion", Slack: "slack", TikTok: "tiktok", Mailchimp: "mailchimp", Canva: "canva" };
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
  return Boolean(PYTHON_OAUTH[toolName]);
}

export async function connectTool(toolName, opts = {}) {
  if (pythonRuntimeEnabled) {
    const provider = PYTHON_OAUTH[toolName];
    if (provider) {
      const result = await authorizeOAuth(provider);
      if (result.redirecting) return { method: "oauth", connected: false, authorizationStarted: true, provider };
      await hydrateConnections();
      return { method: "oauth", connected: true, provider, connection: result.tool };
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

    if (!opts.baseUrl) return { method: "custom", connected: false, needsConfiguration: true };
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
    for (const tool of tools) {
      if (!tool.enabled) continue;
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

export async function getToolConnection(toolName) {
  const tools = await listPythonTools();
  const provider = PYTHON_OAUTH[toolName];
  return tools.find((tool) =>
    tool.display_name === toolName ||
    tool.slug === slugify(toolName) ||
    (provider && (tool.slug === provider || tool.display_name === "Google Workspace"))
  );
}

export async function testToolConnection(toolName) {
  if (!pythonRuntimeEnabled) throw new Error("Connection testing requires the Python control plane.");
  const tool = await getToolConnection(toolName);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  return testPythonConnection(tool.id);
}

export async function disconnectTool(toolName) {
  if (!pythonRuntimeEnabled) throw new Error("Revoking connections requires the Python control plane.");
  const tool = await getToolConnection(toolName);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  await disconnectPythonConnection(tool.id);
  await hydrateConnections();
  return { disconnected: true };
}

export async function reconnectTool(toolName) {
  if (!pythonRuntimeEnabled) throw new Error("Reauthorization requires the Python control plane.");
  const tool = await getToolConnection(toolName);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  const result = await reconnectPythonConnection(tool);
  await hydrateConnections();
  return result;
}

export async function recordInterfaceConnection(toolName, meta = {}) {
  if (pythonRuntimeEnabled) {
    if (!meta.baseUrl) throw new Error("Paste the tool URL before connecting it.");
    return connectTool(toolName, {
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
