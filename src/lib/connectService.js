import { base44 } from "@/api/base44Client";
import { setConnection, replaceConnections } from "@/lib/connectionsStore";
import {
  addPythonTool,
  authorizeOAuth,
  discoverPythonConnector,
  disconnectPythonConnection,
  listPythonTools,
  pythonRuntimeEnabled,
  testPythonConnection,
} from "@/lib/auraApi";

const PYTHON_OAUTH = { Gmail: "google", "Google Drive": "google", "Google Calendar": "google", "Google Sheets": "google", Airtable: "airtable", Slack: "slack" };
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
    for (const tool of tools) map[tool.display_name] = tool.enabled;
    if (map["Google Workspace"]) {
      map.Gmail = true;
      map["Google Drive"] = true;
      map["Google Calendar"] = true;
      map["Google Sheets"] = true;
    }
    replaceConnections(map);
    return tools;
  }
  const res = await base44.functions.invoke("listToolConnections", {});
  replaceConnections(res.data?.connections || {});
  return [];
}

async function findConnection(toolName) {
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
  const tool = await findConnection(toolName);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  return testPythonConnection(tool.id);
}

export async function disconnectTool(toolName) {
  if (!pythonRuntimeEnabled) throw new Error("Revoking connections requires the Python control plane.");
  const tool = await findConnection(toolName);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  await disconnectPythonConnection(tool.id);
  await hydrateConnections();
  return { disconnected: true };
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
