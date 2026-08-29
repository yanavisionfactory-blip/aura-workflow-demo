const API_URL = (import.meta.env.VITE_AURA_API_URL || "").replace(/\/$/, "");
const WORKSPACE_KEY = "aura_python_workspace_id";

export const pythonRuntimeEnabled = Boolean(API_URL);

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
  if (!response.ok) throw new Error(data.detail || data.error || `AURA API failed (${response.status})`);
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

export async function authorizeOAuth(provider) {
  await ensureWorkspace();
  const { authorization_url } = await request(`/v1/oauth/${provider}/start`);
  const popup = window.open(authorization_url, `aura-oauth-${provider}`, "popup,width=620,height=760");
  if (!popup) window.location.assign(authorization_url);
  return { authorization_url };
}

export async function addPythonTool({ slug, displayName, kind = "api_key", baseUrl, credentials, allowedOperations = ["http.request"], config = {} }) {
  await ensureWorkspace();
  return request("/v1/tools", {
    method: "POST",
    body: JSON.stringify({
      slug, display_name: displayName, kind, base_url: baseUrl || null,
      credentials: credentials || {}, config, allowed_operations: allowedOperations,
    }),
  });
}

export async function createPythonRun(prompt, workflowId = null) {
  await ensureWorkspace();
  return request("/v1/runs", {
    method: "POST",
    body: JSON.stringify({ prompt, workflow_id: workflowId }),
  });
}

export async function getPythonRun(runId) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}`);
}

export async function approvePythonPlan(runId, editedSteps = null) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}/approve-plan`, {
    method: "POST",
    body: JSON.stringify({ approved: true, edited_steps: editedSteps }),
  });
}
