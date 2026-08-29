const API_URL = (import.meta.env.VITE_AURA_API_URL || "").replace(/\/$/, "");
const WORKSPACE_KEY = "aura_python_workspace_id";

export const pythonRuntimeEnabled = Boolean(API_URL);

function messageFrom(data, status) {
  const detail = data?.detail ?? data?.error;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  return `AURA API failed (${status})`;
}

async function request(path, options = {}) {
  if (!API_URL) throw new Error("AURA Python API is not configured");
  const workspaceId = options.workspaceId || localStorage.getItem(WORKSPACE_KEY);
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(workspaceId ? { "X-Workspace-Id": workspaceId } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(messageFrom(data, response.status));
  return data;
}

export async function ensureWorkspace() {
  const existing = localStorage.getItem(WORKSPACE_KEY);
  if (existing) return existing;
  const workspace = await request("/v1/workspaces?name=My%20AURA%20Workspace", { method: "POST" });
  localStorage.setItem(WORKSPACE_KEY, workspace.id);
  return workspace.id;
}

export async function listPythonTools() {
  await ensureWorkspace();
  return request("/v1/tools");
}

export async function authorizeOAuth(provider, timeoutMs = 120000) {
  await ensureWorkspace();
  const { authorization_url } = await request(`/v1/oauth/${provider}/start`);
  const popup = window.open(authorization_url, `aura-oauth-${provider}`, "popup,width=620,height=760");
  if (!popup) {
    window.location.assign(authorization_url);
    return { authorization_url, redirecting: true };
  }
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    const tools = await listPythonTools().catch(() => []);
    const connected = tools.find((tool) => tool.enabled && (
      tool.slug === provider || (tool.kind === "oauth" && tool.slug.includes(provider))
    ));
    if (connected) {
      if (!popup.closed) popup.close();
      return { authorization_url, connected: true, tool: connected };
    }
    if (popup.closed) throw new Error("Authorization was cancelled before the connection completed.");
  }
  if (!popup.closed) popup.close();
  throw new Error("Authorization timed out. Please try again.");
}

export async function addPythonTool({ slug, displayName, kind = "api_key", baseUrl, credentials, allowedOperations = ["http.request"], config = {} }) {
  await ensureWorkspace();
  return request("/v1/tools", {
    method: "POST",
    body: JSON.stringify({ slug, display_name: displayName, kind, base_url: baseUrl || null, credentials: credentials || {}, config, allowed_operations: allowedOperations }),
  });
}

export async function discoverPythonConnector({ slug, displayName, kind, baseUrl, credentials = {}, config = {} }) {
  await ensureWorkspace();
  return request("/v1/connectors/discover", {
    method: "POST",
    body: JSON.stringify({ slug, display_name: displayName, kind, base_url: baseUrl, credentials, config }),
  });
}

export async function testPythonConnection(connectionId) {
  await ensureWorkspace();
  return request(`/v1/connections/${connectionId}/test`, { method: "POST" });
}

export async function disconnectPythonConnection(connectionId) {
  await ensureWorkspace();
  return request(`/v1/connections/${connectionId}`, { method: "DELETE" });
}

export async function createPythonRun(prompt, workflowId = null) {
  await ensureWorkspace();
  return request("/v1/runs", { method: "POST", body: JSON.stringify({ prompt, workflow_id: workflowId }) });
}

export async function getPythonRun(runId) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}`);
}

export async function approvePythonPlan(runId, editedSteps = null) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}/approve-plan`, { method: "POST", body: JSON.stringify({ approved: true, edited_steps: editedSteps }) });
}
