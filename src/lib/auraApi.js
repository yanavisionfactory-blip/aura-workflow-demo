const API_URL = (import.meta.env.VITE_AURA_API_URL || "").replace(/\/$/, "");
const WORKSPACE_KEY = "aura_python_workspace_id";
const ACTIVE_RUN_KEY = "aura_active_python_run_id";
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
  }
  if (!response.ok) {
    const error = new Error(messageFrom(data, response.status));
    error.status = response.status;
    error.details = data;
    throw error;
  }
  return data;
}

export const auraRequest = request;

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
  let managedSession = null;
  let managedPopupClosedAt = null;
  let previousUpdatedAt = null;
  const oauthSignal = { current: null };
  const receiveOAuthResult = (event) => {
    if (event.origin !== window.location.origin || event.data?.source !== "aura-oauth") return;
    if (event.data.provider !== provider) return;
    oauthSignal.current = event.data;
  };
  window.addEventListener("message", receiveOAuthResult);
  try {
    await ensureWorkspace();
    const before = await listPythonTools().catch(() => []);
    const existing = before.find((tool) => tool.slug === provider);
    previousUpdatedAt = existing?.updated_at || null;
    const managedStatus = await request("/v1/managed-connectors/status").catch(() => null);
    if (managedStatus?.configured && managedStatus.providers?.includes(provider)) {
      const selected = existing?.id
        ? `?connection_id=${encodeURIComponent(existing.id)}`
        : "";
      managedSession = await request(`/v1/managed-connectors/${provider}/session${selected}`, {
        method: "POST",
      });
      if (managedSession.already_connected) {
        const synced = await request(
          `/v1/managed-connectors/${provider}/sync?external_connection_id=${encodeURIComponent(managedSession.external_connection_id)}`,
          { method: "POST" }
        );
        if (synced.connected) {
          popup.close();
          return { connected: true, reused: true, tool: synced };
        }
      }
      authorization_url = managedSession.connect_link || managedSession.authorization_url;
    } else {
      if (existing?.enabled) {
        popup.close();
        return { connected: true, reused: true, tool: existing };
      }
      ({ authorization_url } = await request(`/v1/oauth/${provider}/start`));
    }
    if (!authorization_url) throw new Error("AURA could not create a secure authorization link.");
  } catch (error) {
    popup.close();
    window.removeEventListener("message", receiveOAuthResult);
    throw error;
  }
  popup.location.assign(authorization_url);
  const started = Date.now();
  try {
    while (Date.now() - started < timeoutMs) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      if (oauthSignal.current?.status === "error") {
        throw new Error(oauthSignal.current.message || "The app did not grant AURA access.");
      }
      if (managedSession) {
        const selected = managedSession.connection_id
          ? `connection_id=${encodeURIComponent(managedSession.connection_id)}`
          : managedSession.external_connection_id
          ? `external_connection_id=${encodeURIComponent(managedSession.external_connection_id)}`
          : "";
        const synced = await request(
          `/v1/managed-connectors/${provider}/sync${selected ? `?${selected}` : ""}`,
          { method: "POST" }
        ).catch((error) => {
          if (error.status && error.status < 500) throw error;
          return null;
        });
        if (synced?.connected) {
          const tools = await listPythonTools().catch(() => []);
          const connected = tools.find((tool) => tool.id === synced.connection_id || tool.slug === provider);
          if (!popup.closed) popup.close();
          return { authorization_url, connected: true, tool: connected || synced };
        }
        if (synced && synced.retryable === false && synced.status === "degraded") {
          throw new Error(
            synced.reason === "authorization_required"
              ? "The selected account did not grant usable access. Choose the account that owns the required resources."
              : "The selected account could not be verified."
          );
        }
        if (popup.closed && oauthSignal.current?.status !== "success") {
          managedPopupClosedAt ||= Date.now();
          if (Date.now() - managedPopupClosedAt > 10000) {
            throw new Error("Authorization was closed before AURA verified the selected account.");
          }
        }
        continue;
      }
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
        throw new Error(
          provider === "jira"
            ? "Jira did not grant access to an available workspace. AURA kept your plan unchanged."
            : "The app did not grant access. AURA kept your plan unchanged."
        );
      }
    }
    if (!popup.closed) popup.close();
    throw new Error(
      provider === "jira"
        ? "Jira did not return an accessible workspace. AURA kept your plan unchanged."
        : "The app did not finish connecting. AURA kept your plan unchanged."
    );
  } finally {
    window.removeEventListener("message", receiveOAuthResult);
  }
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

export function rememberActivePythonRun(runId) {
  if (runId) localStorage.setItem(ACTIVE_RUN_KEY, runId);
}

export function forgetActivePythonRun(runId = null) {
  if (!runId || localStorage.getItem(ACTIVE_RUN_KEY) === runId) {
    localStorage.removeItem(ACTIVE_RUN_KEY);
  }
}

export function rememberedActivePythonRun() {
  return localStorage.getItem(ACTIVE_RUN_KEY);
}

export async function createPythonRun(prompt, workflowId = null, requestKey = null) {
  await ensureWorkspace();
  const result = await request("/v1/runs", {
    method: "POST",
    headers: requestKey ? { "Idempotency-Key": requestKey } : {},
    body: JSON.stringify({ prompt, workflow_id: workflowId }),
  });
  rememberActivePythonRun(result.id);
  return result;
}

export async function getPythonRun(runId) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}`);
}

export async function listPythonRuns({ active = false, limit = 20 } = {}) {
  await ensureWorkspace();
  return request(`/v1/runs?active=${active ? "true" : "false"}&limit=${limit}`);
}

export async function getResumablePythonRun() {
  const remembered = rememberedActivePythonRun();
  if (remembered) {
    try {
      const run = await getPythonRun(remembered);
      if (!["completed", "cancelled"].includes(run.status)) return run;
      forgetActivePythonRun(remembered);
    } catch (error) {
      if (![403, 404].includes(error.status)) throw error;
      forgetActivePythonRun(remembered);
    }
  }
  const [latest] = await listPythonRuns({ active: true, limit: 1 });
  if (latest) rememberActivePythonRun(latest.id);
  return latest || null;
}

export async function approvePythonPlan(runId, editedSteps = null) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}/approve-plan`, {
    method: "POST",
    body: JSON.stringify({
      approved: true,
      edited_steps: editedSteps,
      approve_consequential: false,
    }),
  });
}

export async function decidePythonApproval(approvalId, approved, editedArguments = null) {
  await ensureWorkspace();
  return request(`/v1/approvals/${approvalId}`, {
    method: "POST",
    body: JSON.stringify({ approved, edited_arguments: editedArguments }),
  });
}

export async function resumePythonRun(runId, action = "retry", stepId = null) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify({ action, step_id: stepId }),
  });
}

export async function resumePythonRunAfterConnection(runId, connectionId) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}/resume-after-connection`, {
    method: "POST",
    body: JSON.stringify({ connection_id: connectionId }),
  });
}
