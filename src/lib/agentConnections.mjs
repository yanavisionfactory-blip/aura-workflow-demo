export const AGENT_METHODS = Object.freeze([
  {
    id: "a2a",
    name: "A2A",
    description: "Remote agents with task status, cancellation, and artifacts.",
    endpointPlaceholder: "https://agent.example.com/a2a/v1",
  },
  {
    id: "mcp",
    name: "MCP",
    description: "Agent capabilities exposed as structured MCP tools.",
    endpointPlaceholder: "https://agent.example.com/mcp",
  },
  {
    id: "aura",
    name: "AURA Agent API",
    description: "A custom HTTPS agent using the AURA manifest contract.",
    endpointPlaceholder: "https://agent.example.com",
  },
]);

const clean = (value) => String(value || "").trim().replace(/\s+/g, " ");

export function agentConnectionPayload(draft = {}) {
  const protocol = clean(draft.protocol).toLowerCase();
  if (!AGENT_METHODS.some((method) => method.id === protocol)) {
    throw new Error("Choose A2A, MCP, or AURA Agent API.");
  }
  const name = clean(draft.name);
  const owner = clean(draft.owner);
  const endpoint = clean(draft.endpoint);
  const authentication = clean(draft.authentication || "none").toLowerCase();
  const credential = String(draft.credential || "").trim();
  if (name.length < 2) throw new Error("Enter the agent name.");
  if (owner.length < 2) throw new Error("Enter the agent owner or organization.");
  let parsed;
  try {
    parsed = new URL(endpoint);
  } catch {
    throw new Error("Enter a valid HTTPS agent endpoint.");
  }
  if (parsed.protocol !== "https:") {
    throw new Error("Agent endpoints must use HTTPS.");
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error("Agent URLs cannot include credentials, query parameters, or fragments.");
  }
  if (!["none", "bearer", "api_key"].includes(authentication)) {
    throw new Error("Choose a supported authentication method.");
  }
  if (authentication !== "none" && !credential) {
    throw new Error("Enter the credential required by this agent.");
  }
  const manifestUrl = clean(draft.manifest_url);
  if (manifestUrl) {
    let manifest;
    try {
      manifest = new URL(manifestUrl);
    } catch {
      throw new Error("Enter a valid HTTPS manifest URL.");
    }
    if (manifest.protocol !== "https:") {
      throw new Error("Agent manifest URLs must use HTTPS.");
    }
    if (manifest.username || manifest.password || manifest.search || manifest.hash) {
      throw new Error("Agent URLs cannot include credentials, query parameters, or fragments.");
    }
    if (manifest.origin !== parsed.origin) {
      throw new Error("The manifest URL must use the agent endpoint origin.");
    }
  }
  const dataAccess = String(draft.data_access || "")
    .split(",")
    .map(clean)
    .filter(Boolean);
  const dataRetention = clean(draft.data_retention || "provider-defined");
  const maxRuntimeSeconds = Number(draft.max_runtime_seconds || 30);
  const maxCostUsd = Number(draft.max_cost_usd ?? 5);
  if (dataRetention.length < 2) throw new Error("Describe the agent’s data-retention policy.");
  if (!Number.isFinite(maxRuntimeSeconds) || maxRuntimeSeconds < 5 || maxRuntimeSeconds > 300) {
    throw new Error("Agent runtime must be between 5 and 300 seconds.");
  }
  if (!Number.isFinite(maxCostUsd) || maxCostUsd < 0 || maxCostUsd > 1000) {
    throw new Error("Agent cost ceiling must be between $0 and $1,000.");
  }
  return {
    protocol,
    name,
    owner,
    endpoint: parsed.toString(),
    ...(manifestUrl ? { manifest_url: manifestUrl } : {}),
    authentication,
    ...(credential ? { credential } : {}),
    data_access: [...new Set(dataAccess)],
    data_retention: dataRetention,
    max_runtime_seconds: maxRuntimeSeconds,
    max_cost_usd: maxCostUsd,
  };
}

export function agentPromptHints(prompt, agents = []) {
  const normalized = clean(prompt).toLowerCase();
  if (!normalized) return [];
  return agents
    .filter((agent) => agent?.enabled && agent?.status === "verified")
    .filter((agent) => normalized.includes(clean(agent.name).toLowerCase()))
    .map((agent) => agent.name);
}
