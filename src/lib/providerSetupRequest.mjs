// Public registration details only. No provider credential or client secret is
// accepted, and generating this request never contacts or emails the provider.
export function sitebulbApprovalRequest(detail) {
  if (detail?.code !== "provider_registration_rejected"
    || detail.requires_provider_approval !== true || detail.provider_http_status !== 400
    || !["https://mcp.sitebulb.com/cloud", "https://mcp.sitebulb.com/desktop"].includes(detail.endpoint)) return null;
  let callback;
  try { callback = new URL(detail.callback_url); } catch { return null; }
  if (callback.protocol !== "https:" || callback.username || callback.password
    || callback.search || callback.hash || callback.port
    || callback.pathname !== "/v1/oauth/mcp-agent/callback"
    || !callback.hostname.includes(".") || /(?:^|\.)(?:localhost|local)$/.test(callback.hostname)
    || /^[\d.]+$/.test(callback.hostname)) return null;
  return {
    to: "support@sitebulb.com",
    subject: "AURA Sitebulb MCP: callback approval and access guidance",
    body: `Hello Sitebulb Support,

I am connecting AURA to Sitebulb for a client SEO audit workflow. OAuth client registration returned HTTP 400: "Redirect URI domain is not a supported AI client provider domain."

Client: AURA
Application: https://yanavisionfactory-blip.github.io/aura-workflow-demo/
MCP endpoint: ${detail.endpoint}
OAuth callback: ${callback.href}
Requested scope: mcp:read
Flow: authorization code with PKCE S256, public client and dynamic client registration.

Could you approve AURA's callback domain or explain the supported custom-client registration process?

Please also explain how to confirm access to a shared Cloud workspace or an eligible Desktop or assisted Cloud trial. We have not yet verified an authorized completed client audit. We understand that MCP reads completed audits and cannot start a crawl, so the crawl must first run through Sitebulb itself.

This request is for setup guidance and approval only. Please do not activate a paid subscription or incur charges.

Thank you.`,
  };
}
