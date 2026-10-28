# HubSpot MCP setup

Use `HUBSPOT_CONNECTION_MODE=mcp` when the configured HubSpot client belongs to
Development → MCP Connectors. Leave the default `native` for a standard CRM API
OAuth app. These registrations are not interchangeable.

MCP mode reuses the backend's `HUBSPOT_CLIENT_ID` and `HUBSPOT_CLIENT_SECRET` without
exposing them to the browser. Register the exact public callback
`PUBLIC_URL/v1/oauth/mcp-agent/callback` in HubSpot (or the configured callback
registry override). The managed MCP connection discovers HubSpot's OAuth metadata,
uses S256 PKCE and client-secret POST, and omits native CRM scope strings.

The marketplace prefers the official MCP route in MCP mode. The existing HubSpot
broker name also routes there, so an already-open frontend does not start the
wrong OAuth flow. Existing native connections are not converted or deleted.

After consent, AURA must discover tools and execute the authenticated user-details
read before marking the connection enabled. Grants remain workspace-isolated in
the existing credential vault. Test data should only be written after verifying
the selected portal and the permissions returned by HubSpot.

Production registration inspected on 2026-10-28: app 51259227, client
`e0777561-fa62-48bb-8a48-ac8e46c2b55f`, owned by portal 144938608. Its original
`/v1/oauth/installation/callback` is retained; `/v1/oauth/mcp-agent/callback` was
added with the user's approval. Never copy client secrets into this repository.
