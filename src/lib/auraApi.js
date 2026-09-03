const API_URL = (import.meta.env.VITE_AURA_API_URL || "").replace(/\/$/, "");
const WORKSPACE_KEY = "aura_python_workspace_id";
let tokenProvider = null;

export function setAuraTokenProvider(provider) {
  tokenProvider = provider;
}

export function clearWorkspace() {
  localStorage.removeItem(WORKSPACE_KEY);
}

export function selectWorkspace(workspaceId) {
  localStorage.setItem(WORKSPACE_KEY, workspaceId);
}

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
  const token = tokenProvider ? await tokenProvider() : null;
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(workspaceId ? { "X-Workspace-Id": workspaceId } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && tokenProvider) {
    clearWorkspace();
    window.dispatchEvent(new CustomEvent("aura:session-expired"));
  }
  if (!response.ok) throw new Error(messageFrom(data, response.status));
  return data;
}

export async function ensureWorkspace() {
  const existing = localStorage.getItem(WORKSPACE_KEY);
  if (existing) return existing;
  if (tokenProvider) {
    const workspace = await bootstrapWorkspace();
    return workspace.workspace_id;
  }
  const workspace = await request("/v1/workspaces?name=My%20AURA%20Workspace", { method: "POST" });
  selectWorkspace(workspace.id);
  return workspace.id;
}

export async function bootstrapWorkspace(name = "My AURA Workspace") {
  const workspace = await request(`/v1/auth/bootstrap?name=${encodeURIComponent(name)}`, {
    method: "POST",
    workspaceId: null,
  });
  selectWorkspace(workspace.workspace_id);
  return workspace;
}

export async function listPythonWorkspaces() {
  return request("/v1/workspaces", { workspaceId: null });
}

export async function createPythonWorkspace(name) {
  return request(`/v1/workspaces?name=${encodeURIComponent(name)}`, {
    method: "POST",
    workspaceId: null,
  });
}

export async function listPythonTools() {
  await ensureWorkspace();
  return request("/v1/tools");
}

export async function authorizeOAuth(provider, timeoutMs = 120000) {
  const popup = window.open("about:blank", `aura-oauth-${provider}`, "popup,width=620,height=760");
  if (!popup) {
    throw new Error("Your browser blocked the authorization window. Allow pop-ups for AURA and try again.");
  }
  popup.document.title = "Connecting to AURA";
  popup.document.body.innerHTML = '<main style="font-family:system-ui;background:#0b1020;color:#eef2ff;min-height:100vh;display:grid;place-items:center;margin:0"><div style="text-align:center"><div style="font-size:32px;margin-bottom:12px">◌</div><strong>Preparing secure authorization…</strong><p style="color:#94a3b8;font-size:14px">AURA is checking this connection.</p></div></main>';
  let authorization_url;
  let previousUpdatedAt = null;
  try {
    await ensureWorkspace();
    const before = await listPythonTools().catch(() => []);
    previousUpdatedAt = before.find((tool) => tool.slug === provider)?.updated_at || null;
    ({ authorization_url } = await request(`/v1/oauth/${provider}/start`));
  } catch (error) {
    popup.close();
    throw error;
  }
  popup.location.assign(authorization_url);
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    const tools = await listPythonTools().catch(() => []);
    const connected = tools.find((tool) =>
      tool.enabled &&
      (tool.slug === provider || (tool.kind === "oauth" && tool.slug.includes(provider))) &&
      (!previousUpdatedAt || tool.updated_at !== previousUpdatedAt)
    );
    if (connected) {
      if (!popup.closed) popup.close();
      return { authorization_url, connected: true, tool: connected };
    }
    if (popup.closed) {
      const existing = tools.find((tool) => tool.enabled && tool.slug === provider);
      if (existing && !previousUpdatedAt) return { authorization_url, connected: true, tool: existing };
      throw new Error("Authorization was cancelled before the connection completed.");
    }
  }
  if (!popup.closed) popup.close();
  throw new Error("Authorization timed out. Please try again.");
}

export async function authorizeCustomOAuth(payload, timeoutMs = 120000) {
  const popup = window.open("about:blank", `aura-oauth-${payload.slug}`, "popup,width=620,height=760");
  if (!popup) throw new Error("Your browser blocked the authorization window. Allow pop-ups for AURA and try again.");
  await ensureWorkspace();
  let started;
  try {
    started = await request("/v1/oauth/custom/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    popup.location.assign(started.authorization_url);
  } catch (error) {
    popup.close();
    throw error;
  }
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    const tools = await listPythonTools().catch(() => []);
    const connected = tools.find((tool) => tool.slug === payload.slug && tool.enabled);
    if (connected) {
      if (!popup.closed) popup.close();
      return { connected: true, tool: connected };
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
