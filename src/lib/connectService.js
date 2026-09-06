import { setConnection, replaceConnections } from "@/lib/connectionsStore";
import {
  addPythonTool,
  authorizeCustomOAuth,
  authorizeOAuth,
  discoverPythonConnector,
  disconnectPythonConnection,
  listPythonTools,
  testPythonConnection,
} from "@/lib/auraApi";

const PYTHON_OAUTH = {
  Gmail: "google",
  "Google Drive": "google",
  "Google Calendar": "google",
  "Google Sheets": "google",
  Airtable: "airtable",
  Notion: "notion",
  Slack: "slack",
  TikTok: "tiktok",
  Mailchimp: "mailchimp",
  Canva: "canva",
  HubSpot: "hubspot",
};
const slugify = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const credentialsFor = (opts) => opts.credentials || (opts.apiKey ? { api_key: opts.apiKey } : {});

export function hasStandardOAuth(toolName) {
  return Boolean(PYTHON_OAUTH[toolName]);
}

export async function connectTool(toolName, opts = {}) {
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

export async function hydrateConnections() {
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
  const tool = await findConnection(toolName);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  return testPythonConnection(tool.id);
}

export async function disconnectTool(toolName) {
  const tool = await findConnection(toolName);
  if (!tool) throw new Error(`${toolName} is not connected.`);
  await disconnectPythonConnection(tool.id);
  await hydrateConnections();
  return { disconnected: true };
}

export async function recordInterfaceConnection(toolName, meta = {}) {
  if (!meta.baseUrl) throw new Error("Paste the tool URL before connecting it.");
  return connectTool(toolName, {
      baseUrl: meta.baseUrl,
      connectionKind: "browser",
      credentials: meta.credentials || {},
      config: meta,
  });
}
