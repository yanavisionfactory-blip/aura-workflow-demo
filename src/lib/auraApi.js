import { createFrontendClient } from "@pipedream/sdk/browser";

const API_URL = (import.meta.env.VITE_AURA_API_URL || "").replace(/\/$/, "");
const WORKSPACE_KEY = "aura_python_workspace_id";
const ACTIVE_RUN_KEY = "aura_active_python_run_id";
let tokenProvider = null;

export const pythonRuntimeEnabled = Boolean(API_URL);

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
  const performRequest = async (token) => {
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
    return { response, data };
  };

  let token = tokenProvider ? await tokenProvider() : null;
  let result = await performRequest(token);

  if (result.response.status === 401 && tokenProvider) {
    token = await tokenProvider({ skipCache: true });
    result = await performRequest(token);
  }

  // A transient/expired access token must not destroy the workspace identity.
  // Connections are persisted against that workspace, so clearing it here made
  // healthy apps look disconnected after a reload. Explicit sign-out remains
  // responsible for calling clearWorkspace().
  if (!result.response.ok) {
    const error = new Error(messageFrom(result.data, result.response.status));
    error.status = result.response.status;
    error.details = result.data;
    throw error;
  }
  return result.data;
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

let managedConnectorStatus = null;

export async function getManagedConnectorStatus(refresh = false) {
  await ensureWorkspace();
  if (refresh || !managedConnectorStatus) {
    managedConnectorStatus = await request("/v1/managed-connectors/status");
  }
  return managedConnectorStatus;
}

export async function requestManagedConnector(name) {
  await ensureWorkspace();
  return request("/v1/managed-connectors/requests", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function searchConnectorBrokerApps(query, limit = 30) {
  const normalized = String(query || "").trim().replace(/\s+/g, " ");
  if (normalized.length < 2) return { apps: [], count: 0, backends: {} };
  await ensureWorkspace();
  const params = new URLSearchParams({ q: normalized, limit: String(limit) });
  return request(`/v1/connector-broker/apps?${params.toString()}`);
}

export async function createConnectorBrokerSession(provider, connectionId = null) {
  await ensureWorkspace();
  const params = new URLSearchParams();
  if (connectionId) params.set("connection_id", connectionId);
  const query = params.size ? `?${params.toString()}` : "";
  return request(`/v1/connector-broker/${encodeURIComponent(provider)}/session${query}`, {
    method: "POST",
  });
}

export async function completeConnectorBrokerConnection(provider, accountId, connectionId = null) {
  await ensureWorkspace();
  return request(`/v1/connector-broker/${encodeURIComponent(provider)}/complete`, {
    method: "POST",
    body: JSON.stringify({ account_id: accountId, connection_id: connectionId }),
  });
}

export async function syncManagedConnector(provider, connection = {}) {
  await ensureWorkspace();
  const params = new URLSearchParams();
  if (connection.connectionId) params.set("connection_id", connection.connectionId);
  if (connection.externalConnectionId) params.set("external_connection_id", connection.externalConnectionId);
  const query = params.size ? `?${params.toString()}` : "";
  return request(`/v1/managed-connectors/${provider}/sync${query}`, { method: "POST" });
}

const authorizationWindowContent = (reconnecting) => '<main style="font-family:system-ui;background:#0b1020;color:#eef2ff;min-height:100vh;display:grid;place-items:center;margin:0"><div style="text-align:center"><div style="font-size:32px;margin-bottom:12px">◌</div><strong>'
  + (reconnecting ? "Preparing secure reauthorization…" : "Preparing your secure connection…")
  + '</strong><p style="color:#94a3b8;font-size:14px">AURA handles setup and verifies access after you approve it.</p></div></main>';

export function reserveAuthorizationWindow(provider, reconnecting = false) {
  const action = reconnecting ? "reconnect" : "connect";
  const popup = window.open("about:blank", `aura-${action}-${provider}`, "popup,width=620,height=760");
  if (!popup) {
    throw new Error("Your browser blocked the authorization window. Allow pop-ups for AURA and try again.");
  }
  popup.document.title = reconnecting ? "Reconnecting to AURA" : "Connecting to AURA";
  popup.document.body.innerHTML = authorizationWindowContent(reconnecting);
  return popup;
}

function authorizationWindow(provider, reconnecting, reservedWindow) {
  if (reservedWindow && !reservedWindow.closed) return reservedWindow;
  return reserveAuthorizationWindow(provider, reconnecting);
}

export async function authorizeManagedConnector(provider, timeoutMs = 120000, reservedWindow = null, preparedSession = null) {
  const popup = authorizationWindow(provider, false, reservedWindow);
  let session;
  try {
    await ensureWorkspace();
    session = preparedSession || await request(`/v1/managed-connectors/${provider}/session`, { method: "POST" });
    if (session.connect_link) popup.location.assign(session.connect_link);
    else if (!session.already_connected) throw new Error("AURA could not prepare this connection.");
  } catch (error) {
    popup.close();
    throw error;
  }
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    const result = await syncManagedConnector(provider, {
      connectionId: session.tool_connection_id,
      externalConnectionId: session.external_connection_id,
    }).catch(() => null);
    if (result?.connected) {
      const verification = await testPythonConnection(result.tool_id || result.connection_id).catch(() => null);
      if (verification?.status === "verified" && verification.verification?.ok === true) {
        if (!popup.closed) popup.close();
        const tools = await listPythonTools();
        return {
          connected: true,
          managed: true,
          tool: tools.find((tool) => tool.id === (result.tool_id || result.connection_id)),
        };
      }
    }
  }
  if (!popup.closed) popup.close();
  throw new Error("The app did not finish connecting. AURA kept your plan unchanged.");
}

export async function authorizeOAuth(provider, timeoutMs = 120000, reservedWindow = null, preparedSession = null) {
  const popup = authorizationWindow(provider, false, reservedWindow);
  let authorization_url;
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
    if (existing?.enabled && !preparedSession) {
      popup.close();
      window.removeEventListener("message", receiveOAuthResult);
      return { connected: true, reused: true, tool: existing };
    }
    previousUpdatedAt = preparedSession?.previous_updated_at || existing?.updated_at || null;
    ({ authorization_url } = preparedSession || await request(`/v1/oauth/${provider}/start`));
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

async function authorizePipedreamConnector(provider, session, timeoutMs) {
  const tokenCallback = async () => {
    const refreshed = await createConnectorBrokerSession(provider, session.connection_id);
    return {
      token: refreshed.token,
      expiresAt: refreshed.expires_at ? new Date(refreshed.expires_at) : new Date(Date.now() + 60000),
      connectLinkUrl: "",
    };
  };
  const client = createFrontendClient({
    externalUserId: session.external_user_id,
    projectEnvironment: session.project_environment,
    token: session.token,
    tokenCallback,
  });

  return new Promise((resolve, reject) => {
    let settled = false;
    let completion = null;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      document.querySelectorAll('iframe[id^="pipedream-connect-iframe-"]').forEach((frame) => frame.remove());
      callback(value);
    };
    const timer = window.setTimeout(() => {
      document.querySelectorAll('iframe[id^="pipedream-connect-iframe-"]').forEach((frame) => frame.remove());
      finish(reject, new Error("The app did not finish connecting. AURA kept your plan unchanged."));
    }, timeoutMs);

    client.connectAccount({
      app: session.app || provider,
      token: session.token,
      accountId: session.account_id || undefined,
      customOauthClient: false,
      onSuccess: ({ id }) => {
        completion = completeConnectorBrokerConnection(
          provider,
          id,
          session.connection_id,
        ).then(async (result) => {
          const tools = await listPythonTools();
          const tool = tools.find((item) => item.id === result.connection_id);
          if (!tool) throw new Error(`${provider} access could not be verified.`);
          return { connected: true, managed: true, backend: "pipedream", tool };
        });
        completion.then(
          (result) => finish(resolve, result),
          (error) => finish(reject, error),
        );
      },
      onError: (error) => finish(
        reject,
        new Error(error?.message || "The provider did not grant AURA access."),
      ),
      onClose: ({ successful }) => {
        if (successful && completion) return;
        finish(reject, new Error("Connection was cancelled. AURA kept your plan unchanged."));
      },
    }).then(() => {
      document.querySelectorAll('iframe[id^="pipedream-connect-iframe-"]').forEach((frame) => {
        frame.title = `Connect ${provider}`;
      });
    }).catch((error) => finish(reject, error));
  });
}

export async function authorizeConnectorBroker(
  provider,
  { connection = null, timeoutMs = 120000, reservedWindow = null } = {},
) {
  let session;
  try {
    session = await createConnectorBrokerSession(provider, connection?.id || null);
  } catch (error) {
    if (reservedWindow && !reservedWindow.closed) reservedWindow.close();
    throw error;
  }
  if (session.backend === "pipedream") {
    if (reservedWindow && !reservedWindow.closed) reservedWindow.close();
    return authorizePipedreamConnector(provider, session, timeoutMs);
  }
  if (session.backend === "nango") {
    return authorizeManagedConnector(provider, timeoutMs, reservedWindow, session);
  }
  if (session.backend === "native") {
    return authorizeOAuth(provider, timeoutMs, reservedWindow, session);
  }
  if (reservedWindow && !reservedWindow.closed) reservedWindow.close();
  throw new Error("AURA could not select a secure connection route for this app.");
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

export async function reconnectPythonConnection(connection, timeoutMs = 120000, reservedWindow = null) {
  const popup = authorizationWindow(connection.slug || connection.id, true, reservedWindow);
  let started;
  try {
    await ensureWorkspace();
    started = await request(`/v1/connections/${connection.id}/reconnect`, { method: "POST" });
    popup.location.assign(started.authorization_url);
  } catch (error) {
    popup.close();
    throw error;
  }
  const baseline = started.previous_updated_at || connection.updated_at || null;
  const startedAt = Date.now();
  let closedAt = null;
  while (Date.now() - startedAt < timeoutMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    if (started.managed) {
      const synced = await syncManagedConnector(connection.slug, {
        connectionId: connection.id,
        externalConnectionId: connection.external_connection_id,
      }).catch(() => null);
      if (synced?.connected) {
        const verification = await testPythonConnection(connection.id).catch(() => null);
        if (verification?.status === "verified" && verification.verification?.ok === true) {
          if (!popup.closed) popup.close();
          const tools = await listPythonTools();
          return { connected: true, managed: true, tool: tools.find((tool) => tool.id === connection.id) };
        }
      }
    }
    const tools = await listPythonTools().catch(() => []);
    const updated = tools.find((tool) =>
      tool.id === connection.id && tool.enabled && (!baseline || tool.updated_at !== baseline)
    );
    if (updated) {
      if (!popup.closed) popup.close();
      return { connected: true, tool: updated };
    }
    if (popup.closed && !started.managed) {
      closedAt ||= Date.now();
      if (Date.now() - closedAt > 15000) {
        throw new Error("AURA could not verify the restored access. Your work is preserved.");
      }
    }
  }
  if (!popup.closed) popup.close();
  throw new Error("Reauthorization timed out. Please try again.");
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

export async function createPythonRun(prompt, workflowId = null, requestKey = null, inputs = {}) {
  await ensureWorkspace();
  const run = await request("/v1/runs", {
    method: "POST",
    headers: requestKey ? { "Idempotency-Key": requestKey } : {},
    body: JSON.stringify({ prompt, workflow_id: workflowId, inputs }),
  });
  rememberActivePythonRun(run.id);
  return run;
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

export async function approvePythonPlan(runId, editedSteps = null, approveConsequential = false) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}/approve-plan`, { method: "POST", body: JSON.stringify({ approved: true, edited_steps: editedSteps, approve_consequential: approveConsequential }) });
}

export async function decidePythonApproval(approvalId, approved, editedArguments = null) {
  await ensureWorkspace();
  return request(`/v1/approvals/${approvalId}`, {
    method: "POST",
    body: JSON.stringify({ approved, edited_arguments: editedArguments }),
  });
}

export async function resumePythonRun(runId, stepId = null, action = "retry") {
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

export async function cancelPythonRun(runId) {
  await ensureWorkspace();
  return request(`/v1/runs/${runId}/cancel`, { method: "POST" });
}
