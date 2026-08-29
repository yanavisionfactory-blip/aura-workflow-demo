// AURA's connection intelligence registry.
//
// For each tool AURA might need, this encodes the connection method the agent
// has chosen — without ever asking the user. Three methods:
//   oauth     — the tool has a standard shared OAuth connector. The builder
//               authorizes it once (no client secrets, no per-user setup);
//               every app user then shares that authorized connection.
//   mcp       — the tool exposes an MCP server AURA can call directly
//   interface — no standard integration; AURA learns the tool's web interface
//
// The user never sees which method was chosen — they only approve access.

export const TOOL_REGISTRY = {
  Gmail: {
    method: "oauth",
    connector: "gmail",
    connectorId: null,
    scopes: [
      "https://www.googleapis.com/auth/gmail.send",
      "https://www.googleapis.com/auth/gmail.readonly",
    ],
  },
  Airtable: {
    method: "oauth",
    connector: "airtable",
    connectorId: null,
    scopes: ["data.records:read", "data.records:write", "schema.bases:read"],
  },
  Slack: { method: "oauth", connector: "slack", connectorId: null },
  Salesforce: { method: "oauth", connector: "salesforce", connectorId: null },
  "Google Calendar": { method: "oauth", connector: "googlecalendar", connectorId: null },
  "Google Drive": { method: "oauth", connector: "googledrive", connectorId: null },
  "Google Sheets": { method: "oauth", connector: "googlesheets", connectorId: null },
  Notion: { method: "oauth", connector: "notion", connectorId: null },
  HubSpot: { method: "oauth", connector: "hubspot", connectorId: null },
  "Meta Ads": { method: "oauth", connector: "meta_ads", connectorId: null },
  Jira: { method: "oauth", connector: "jira", connectorId: null },
  Instagram: { method: "oauth", connector: "instagram", connectorId: null },
  QuickBooks: { method: "oauth", connector: "quickbooks", connectorId: null },
  // Internal approval tool — no standard OAuth API. AURA learns its web
  // interface through the AURA Interface learn flow.
  "Creator Approvals": { method: "interface" },
  // Specialized creator-data APIs — API-key auth. The key lives in the
  // ToolConnection meta; the orchestrator reads it to call the real API.
  // Without a key, AURA falls back to LLM discovery and marks it unverified.
  Modash: { method: "api_key", specialty: "creator-data" },
  HypeAuditor: { method: "api_key", specialty: "creator-data" },
  Apify: { method: "api_key", specialty: "scraping" },
  // Shopify publishes an internal MCP server — AURA connects via MCP, no OAuth.
  Shopify: { method: "mcp", mcpServerUrl: "https://mcp.shop.internal/orders" },
};

export function getRegistryEntry(toolName) {
  return TOOL_REGISTRY[toolName] || null;
}