// Normal-user connection policy. Every tool listed here has a backend-owned
// OAuth implementation; anything else must be provisioned backstage and must
// never fall through to an API-key, MCP, or interface-configuration form.
export const MANAGED_OAUTH_PROVIDER_BY_TOOL = Object.freeze({
  Gmail: "google",
  "Google Drive": "google",
  "Google Calendar": "google",
  "Google Sheets": "google",
  Jira: "jira",
  Airtable: "airtable",
  Notion: "notion",
  Slack: "slack",
  TikTok: "tiktok",
  Mailchimp: "mailchimp",
  Canva: "canva",
  HubSpot: "hubspot",
});

export function managedOAuthProviderFor(toolName) {
  return MANAGED_OAUTH_PROVIDER_BY_TOOL[String(toolName || "").trim()] || null;
}

export function isManagedOAuthTool(toolName) {
  return Boolean(managedOAuthProviderFor(toolName));
}

export function userConnectionRoute(toolName) {
  const provider = managedOAuthProviderFor(toolName);
  return provider
    ? { kind: "managed_oauth", provider }
    : { kind: "backstage_only", provider: null };
}
