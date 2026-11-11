# AURA inside ChatGPT: private MCP pilot

Status: implemented behind an opt-in flag. Live Clerk consent and ChatGPT
installation must pass before calling the integration connected or available to
external users. This is not Sign in with ChatGPT in AURA; the user works inside
ChatGPT and grants access to their AURA account. No end-user OpenAI API key is used.

## Pilot surface

| Tool | Permission | Behavior |
| --- | --- | --- |
| `list_workspaces` | `aura:read` | Lists existing active workspaces for the OAuth identity |
| `list_connections` | `aura:read` | Lists tool names and enabled status, without credentials or account content |
| `list_workflows` | `aura:read` | Lists saved workflow names and IDs |
| `get_workflow` | `aura:read` | Reads the selected workflow's task description, without variables or run outputs |
| `save_workflow_draft` | `aura:read aura:drafts:write` | Saves a disabled workflow; retries use the same `request_key` |

There are no run, approve, schedule, send, delete or provider execution tools.
Draft creation does not invoke AURA's model or consume its API inference budget.
Users review the saved draft before separately enabling or executing it in AURA.

## Clerk setup

Use the same Clerk instance as the live AURA application. Do not create a parallel
identity store. Clerk handles consent, authorization codes, PKCE and refresh.

1. In Clerk's OAuth applications, add custom scopes:
   - `aura:read`: View your AURA workspace names, connected tool names and saved workflow descriptions.
   - `aura:drafts:write`: Save disabled workflow drafts in your AURA workspaces. Does not run workflows.
2. Add this MCP resource under Agents → MCP servers:
   `https://impartial-emotion-production-49d4.up.railway.app/mcp`.
   Enable audience claims for this exact resource and JWT access tokens.
3. Enable CIMD support and require PKCE S256. Keep the consent screen enabled.
   Advertise the two custom scopes; configure defaults if the client omits scope.
   Do not grant profile, email, private metadata or unrelated service scopes.
4. The backend accepts the exact client ID `https://chatgpt.com/oauth/client.json`
   by default. If ChatGPT uses a callback-specific CIMD document or a static
   Clerk OAuth application, copy that exact registered client ID into
   `CHATGPT_MCP_ALLOWED_CLIENT_IDS` (comma-separated). Never use a wildcard.
   For static registration, use only the callback shown by ChatGPT.
5. The initial pilot uses personal AURA workspaces. Organization access is
   accepted only when Clerk explicitly issues `org_id` with `user:org:read`;
   the user must also have an active AURA membership. Do not add that scope to
   a grant without reviewing the organization-selection experience.

Clerk JWT verification checks RS256, access-token type, exact issuer and audience,
expiry, user identity, allowed client and granted scopes. Browser session JWTs,
ID tokens, opaque tokens and legacy workspace tokens are rejected. Tenant
membership is checked on every tool call. Removing membership blocks access
immediately; Clerk JWT token revocation alone can take until token expiry.

## Deployment and connection

1. Merge only after backend CI passes. Use the normal tested-main release
   workflow, including canary, worker and API checks.
2. Configure the API service with `CHATGPT_MCP_ENABLED=true` only after Clerk
   setup. Existing `CLERK_ISSUER`, `CLERK_JWT_KEY` or `CLERK_JWKS_URL`,
   `PUBLIC_URL`, and `FRONTEND_URL` are reused. `PUBLIC_URL` must be the canonical
   HTTPS API origin. Leave the worker unchanged. Canary mode never mounts MCP.
3. Verify public protected-resource metadata at
   `/.well-known/oauth-protected-resource/mcp`. It must advertise the exact
   resource and Clerk issuer. Unauthenticated `/mcp` requests must return 401
   with the metadata challenge, and an unexpected Host must be rejected.
4. In ChatGPT, Plugins → + → Add custom MCP server, name it **AURA**, enter the
   `/mcp` URL, choose OAuth, and review the discovered tools. Install privately
   for the pilot; no directory publication is implied.
5. Complete AURA sign-in and explicit consent. In a new chat, select `@AURA`
   and ask: "List my AURA workspaces and connected tools."
6. Ask to save a clearly named pilot draft, inspect it with `get_workflow`, and
   verify in AURA that it is disabled and no run was created. Repeat the request
   with the same key to verify that no duplicate appears.
7. Use a second account to verify isolation and fresh-user onboarding, then test
   reconnect, expiry/refresh, denied consent, and removal of workspace access.
   An account without an existing AURA workspace must first sign in to AURA.

Rollback: set `CHATGPT_MCP_ENABLED=false` on the API and redeploy through the
normal release process. This removes MCP access without changing browser login
or existing workflows. Revoke the pilot grant in Clerk/ChatGPT as appropriate.

Automated tests cover transport authentication, invalid tokens, tool discovery,
tenant isolation, disabled/revoked memberships, secret filtering, scope upgrades,
draft retry behavior, no execution, hostile Host rejection, and lifecycle mounting.
They do not prove live OAuth consent, client registration, refresh, or ChatGPT installation.

References:
- https://developers.openai.com/plugins/deploy/connect-chatgpt
- https://developers.openai.com/plugins/build/auth
- https://clerk.com/docs/nextjs/guides/ai/mcp/build-mcp-server
- https://clerk.com/docs/guides/configure/auth-strategies/oauth/how-clerk-implements-oauth
