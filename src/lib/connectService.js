import { base44 } from "@/api/base44Client";
import { setConnection, replaceConnections } from "@/lib/connectionsStore";
import { addPythonTool, authorizeOAuth, listPythonTools, pythonRuntimeEnabled } from "@/lib/auraApi";

const PYTHON_OAUTH = { Gmail: "google", "Google Calendar": "google", "Google Sheets": "google", Airtable: "airtable", Slack: "slack" };
const slugify = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// AURA's connect flow. The user clicks "Connect" — AURA asks the backend which
// method is best (oauth / mcp / interface), then connects behind the scenes.
// The user never sees which method was chosen; they only approve access.
//
// Returns { method, interfaceTool, connected }:
//   - interfaceTool is set ONLY when the AURA Interface learn flow must open
//     (the one method that needs a user-facing UI). oauth and mcp connect
//     silently and return connected: true.

export async function connectTool(toolName, opts = {}) {
  if (pythonRuntimeEnabled) {
    const provider = PYTHON_OAUTH[toolName];
    if (provider) {
      await authorizeOAuth(provider);
      return { method: "oauth", connected: false, authorizationStarted: true, provider };
    }
    if (opts.apiKey || opts.baseUrl) {
      const kind = opts.connectionKind || (opts.baseUrl ? "openapi" : "api_key");
      await addPythonTool({ slug: slugify(toolName), displayName: toolName, kind, baseUrl: opts.baseUrl, credentials: opts.apiKey ? { api_key: opts.apiKey } : opts.credentials, allowedOperations: opts.allowedOperations || ["http.request"] });
      setConnection(toolName, true);
      return { method: kind, connected: true };
    }
    return { method: "custom", connected: false, needsConfiguration: true };
  }

  const res = await base44.functions.invoke("resolveToolConnection", { tool: toolName });
  const info = res.data;
  const method = info.method;

  if (method === "interface") {
    // Defer to the AURA Interface learn flow — the caller opens the modal.
    return { method, interfaceTool: toolName, connected: false };
  }

  if (method === "api_key") {
    // Specialized API-key tools (Modash, HypeAuditor, Apify). The user pastes
    // their API key; we persist it in the ToolConnection meta so the orchestrator
    // can call the real API. No real key = not connected.
    if (!opts.apiKey) {
      return { method, interfaceTool: null, connected: false, needsApiKey: true };
    }
    await base44.functions.invoke("recordToolConnection", {
      tool: toolName,
      method,
      meta: { apiKey: opts.apiKey },
    });
    setConnection(toolName, true);
    return { method, interfaceTool: null, connected: true };
  }

  if (method === "oauth") {
    // Shared OAuth only. The builder authorizes the connector once (no client
    // secrets, no per-user setup); every app user shares that connection.
    // Only a real authorized token counts — never fake a connection.
    if (info.oauthAuthorized) {
      setConnection(toolName, true);
      return { method, interfaceTool: null, connected: true };
    }
    return {
      method,
      interfaceTool: null,
      connected: false,
      needsAuthorization: true,
      connector: info.connector,
    };
  }

  // mcp — a custom integration backed by an MCP server URL. Persist it and
  // mark connected (the orchestrator calls the MCP server directly).
  await base44.functions.invoke("recordToolConnection", {
    tool: toolName,
    method,
    meta: { mcpServerUrl: info.mcpServerUrl },
  });
  setConnection(toolName, true);
  return { method, interfaceTool: null, connected: true };
}

// Called once on app load. Pulls the real connection map from the backend
// (live OAuth status + persisted interface/mcp connections) and syncs the
// shared store, so every module reflects what AURA actually has access to.
export async function hydrateConnections() {
  try {
    if (pythonRuntimeEnabled) {
      const tools = await listPythonTools();
      const map = {};
      for (const tool of tools) map[tool.display_name] = tool.enabled;
      if (map["Google Workspace"]) { map.Gmail = true; map["Google Calendar"] = true; map["Google Sheets"] = true; }
      replaceConnections(map);
      return;
    }
    const res = await base44.functions.invoke("listToolConnections", {});
    const map = res.data?.connections || {};
    replaceConnections(map);
  } catch {
    // Backend unavailable — keep current in-memory state.
  }
}

// Called from the AURA Interface learn flow once the user finishes learning a
// custom tool. Persists it as an interface connection.
export async function recordInterfaceConnection(toolName, meta = {}) {
  try {
    await base44.functions.invoke("recordToolConnection", {
      tool: toolName,
      method: "interface",
      meta,
    });
  } catch {
    // non-fatal — store still updates
  }
  setConnection(toolName, true);
}