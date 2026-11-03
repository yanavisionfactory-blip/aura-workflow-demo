# Connector authorization operations

Connection setup belongs to the shared backend, not an individual workflow.
Connect and reconnect requests run a fresh preflight, bounded to ten seconds,
before a user authorization session is issued. Healthy connected workflow steps
do not perform this extra configuration read.

## Configuration ownership

New Canva accounts use Pipedream Connect's managed Canva OAuth client. This is
the public-user route: the customer signs into Canva and grants consent, and
AURA keeps a tenant-scoped opaque account reference. Customers do not need a
Nango or Pipedream login or their own OAuth app. Use
`PIPEDREAM_ENVIRONMENT=production` for the public deployment. Pipedream's managed
client supports action execution and API proxying; do not export its tokens.

Canva's Pipedream action contract must pass the normal schema/signature
certification before the marketplace enables Connect. A Nango API key or legacy
`CANVA_CLIENT_ID` alone must not mark this public route available. New connections
must not fall back to the legacy Nango/native app when Pipedream is unavailable.
Existing Nango/native accounts keep their backend; existing Pipedream accounts
also keep their recorded environment, including when reconnecting without an
explicit connection ID. This change does not rotate or overwrite credentials.

Release verification requires a fresh customer connection in production mode,
the customer's Canva consent, and a successful account ownership/health probe.
Passing unit tests or opening the consent window alone is not an end-to-end
connection test. See Pipedream's [OAuth client support](https://pipedream.com/docs/connect/managed-auth/oauth-clients)
and [Canva connector](https://pipedream.com/apps/canva).

Existing OAuth integration credentials belong to Nango. Backend environment
credentials are used only to provision a missing integration. Updating environment
variables does not repair an existing Nango integration. Never automatically
overwrite an existing integration's client ID or secret: that can invalidate
refresh tokens for every connected account.

Mailchimp's registered AURA app uses the native installation callback. When
`MAILCHIMP_CLIENT_ID` and `MAILCHIMP_CLIENT_SECRET` are configured, a *new*
Mailchimp connection starts on that native route so its signed state and
callback agree. Existing connections keep the backend recorded with their
account; a generic Connect action must not migrate them. If using a separate
Nango Mailchimp app, register Nango's callback against that app's own client ID
before offering it. The provider's callback registration and a real consent
test still need operator verification; structural preflight alone cannot prove
either. A foreign or invalid state at AURA's callback is rejected without a
token exchange and returned to the app as a connection error.

TikTok's registered AURA app also uses the native installation callback. New
TikTok connections go directly to TikTok Login Kit, even when Nango is enabled;
Nango's availability alone does not establish a working TikTok integration.
Both `TIKTOK_CLIENT_ID` (TikTok's client key) and `TIKTOK_CLIENT_SECRET` must be
configured before the marketplace offers that route. Existing managed accounts
keep their recorded backend. Register the exact
`<PUBLIC_URL>/v1/oauth/installation/callback` URI in TikTok Login Kit (or the
explicit callback override), and approve the requested products and scopes in
TikTok's developer portal. App review and an authenticated profile read are
still required to verify live access; reaching TikTok's login page is not a
successful account connection. TikTok Ads Manager is a separate connector.

The marketplace features **TikTok**, **TikTok Ads**, and **X (Twitter)** at the
start of the directory. "TikTok Ads" selects the signed Pipedream
`tiktok-ads-manager` pack (vendor ID `tiktok_ads_manager`), with the project's
production environment and a separate opaque identity for each external user.
It does not use the personal TikTok Login Kit app. Catalog aliases group legacy
discovery rows without renaming stored accounts or their authorization routes.
Existing grants retain their original backend and environment.

X uses an AURA-owned OAuth 2.0 confidential web app. Configure `X_CLIENT_ID` and
`X_CLIENT_SECRET` on both API and worker, and register the exact
`<PUBLIC_URL>/v1/oauth/installation/callback` URL in the X developer console.
Enable user authentication and the `users.read`, `tweet.read`, `tweet.write`,
and `offline.access` scopes. The application must have X API access for its
requested endpoints. End users authorize their own X accounts; they never
supply developer API keys. The public route stays unavailable until both
server-side client credentials are configured. Nango availability alone cannot
enable it. Each authorization has tenant-bound signed state and an S256 PKCE
challenge; the verifier and client secret stay on the server. A successful
token response is followed by `GET /2/users/me` before saving the account.
Refresh token rotation preserves the connection identity. Post creation uses
the ordinary workflow approval gate and requires X's returned post ID.

Production release checks do not prove provider consent. Verify a fresh
external-user authorization separately for each provider. TikTok must show
**Live** in its production developer configuration; sandbox/test-user access
does not enable arbitrary external users. No new vendor subscription or API
credit purchase is part of this configuration.

Use an explicit integration map when multiple integrations match a provider.
An exact provider-named integration is preferred; otherwise there must be exactly
one match. Explicit mappings are checked against the returned integration identity
and provider before issuing an authorization link.

## Dynamic Connector Engineer

`CONNECTOR_ENGINEER_ENABLED=true` starts a control-plane loop independent of
workflow delivery. Each scan reads Nango's provider, integration, and deployed
function catalogs and compiles eligible OAuth2 integrations into data-only AURA
capability packs. Provider code is never downloaded or executed in the API
process. The only permitted runtime transports are Nango action invocation and
Nango synchronized-record reads against the configured Nango origin.

The complete safe provider metadata snapshot is persisted and returned as the
searchable `marketplace` field. Entries that are merely discovered are labelled
`verifying` (or `unsupported_auth`) and cannot create a customer connection.
Only the separate signed `catalog` receives a Connect action. Bounded scans use a
durable rotating cursor, so a large Nango catalog is reconciled across successive
ticks instead of repeatedly processing the same first page.

A discovered integration is not a supported connector. A version becomes visible
to planning and `GET /v1/managed-connectors/status` only after all of these gates:

1. Every module and JSON Schema passes isolated validation.
2. The normalized immutable definition is hashed and HMAC-signed by AURA.
3. Every operation passes against the dedicated Nango connection configured in
   `CONNECTOR_ENGINEER_CANARY_CONNECTIONS_JSON`.
4. The release transitions to `released`. Failed candidates remain `rejected` and
   cannot supersede the last good release.

Released definitions are versioned globally; customer connection references
remain tenant-scoped. Runtime execution verifies the stored release ID, hash,
signature, provider, integration, and release state before calling Nango. A
tampered, quarantined, or rolled-back pack is not executable or user-visible.
Repeated canary failures quarantine the active version and reactivate a valid
previous release when one exists.

The customer flow remains one click plus the provider's official consent: AURA
creates a Nango Connect session restricted to the exact released integration,
the customer authorizes in the provider popup, AURA probes the granted scopes and
safe read operations, stores only the Nango connection reference, and resumes the
saved workflow. API keys, MCP endpoints, raw OAuth forms, and provider tokens are
never requested from or shown to the customer.

An empty canary map intentionally yields `awaiting_canary`, not a partially
supported connector. Nango catalog entries without an operator-owned integration
and deployed functions may be found in marketplace search, but remain disabled
and never expose API keys, endpoints, or OAuth configuration. Do not describe the
product as supporting arbitrary tools merely because Nango lists a provider;
only the signed `released` catalog is executable.

## Preflight evidence and limits

Nango must permit reading integration credentials (`include=credentials`). The
backend checks credential presence, OAuth2 type, whitespace, known placeholders,
ID/secret equality, and Canva's Connect client ID shape. Credentials are used
transiently and are never included in diagnostic output. A passing check does not
prove that the provider accepts a secret, permits the requested scopes, has approved
the app, or has registered the callback. A well-formed but incorrect client ID can
still fail at the provider.

Before offering a provider in production, the operator must record a real
authorization and refresh test for the actual Nango environment and integration.
Check the provider portal's client ID against Nango, verify the callback shown by
Nango is registered in that same provider integration, and confirm the required
scopes and app distribution rules. Re-run this check after credential, callback,
scope, or environment changes. Do not infer certification from unit tests.

## Failure handling

`managed_connector_preflight_failed` logs a provider and fixed configuration code.
Missing credentials, mismatched provider/identity, ambiguous mapping, and malformed
IDs are operator-owned corrections. They must not be diagnosed as an end-user
password problem. The existing error response preserves the workflow and explains
that signing in again will not fix configuration. Upstream error bodies are not
logged because they may echo secrets.

A timeout is a temporary availability failure and returns within the preflight
budget. No authorization POST is issued on a failed preflight. Configuration
repairs are read on the next attempt; there is no cached failure or process restart
requirement. Once corrected, start a fresh authorization session rather than reuse
an old OAuth link.

Before changing a client ID, inspect existing connections and arrange reauthorization
for affected accounts. Preserve unrelated integrations and existing secrets during
a planned rotation. Never bypass user consent, account selection, or provider MFA.

## Release checks

The shared regression suite covers every registered OAuth provider, malformed and
missing credentials, cross-provider mappings, ambiguous discovery, corrected
configuration on retry, reconnect, preflight timeout, rejected provisioning, and
credential redaction. It runs in the normal backend release suite. No per-workflow
database or connector-specific customer workaround is needed.

Connector Engineer tests additionally cover transport isolation, schema
compilation, exact integration scoping, dedicated-account canaries, signature
tamper rejection, failed-candidate containment, previous-release preservation,
rotating large-catalog coverage, customer capability probes, and Nango
action/record execution. Administrators can
inspect `GET /v1/admin/connector-engineer` and trigger a bounded reconciliation
with `POST /v1/admin/connector-engineer/scan`; neither endpoint returns credentials.
# Zernio: public TikTok and X connections

AURA owns one Zernio team and its server API key. Customers use their normal
TikTok/X accounts; they do not create a Zernio account, install a plugin, supply
developer credentials, or visit Zernio billing. The provider consent screen may
name Zernio. Zernio currently shows a one-click exit notice before returning to
AURA; that page is not a Zernio sign-in.

Activation:

1. Create the AURA-owned account at https://zernio.com and generate a server API
   key. X requires a payment method on that team, including within the free
   connected-account allowance. Account fees and X usage are billed to AURA.
2. Save `ZERNIO_API_KEY` on the Railway API, worker and recovery canary. Use the
   same key on all three. Never put it in `VITE_` settings, source code, browser
   storage or customer connection forms. Keep existing Pipedream production and
   legacy variables unchanged.
3. Run the existing **Backend Release** workflow on the tested main-branch SHA.
   Follow its canary → worker → API gates. Verify `/ready` on API and canary and
   successful new worker deployment before enabling customer testing.
4. From a fresh AURA customer session without a Zernio session, choose Connect →
   TikTok or X, complete provider consent, continue back to AURA and run Test.
   Verify the account's identity and a read operation. Repeat with a second
   customer and confirm neither can see or use the other's account.

Routes are `tiktok-zernio` and `x-zernio`, grouped into the existing TikTok/X
cards. Once the key is configured, these are preferred for new connections.
Native, Nango and Pipedream accounts keep their stored backend and grants.
TikTok Ads stays on Pipedream. Missing credentials never make a route connectable.

One opaque Zernio profile is provisioned per AURA workspace. A compact signed,
15-minute, single-use authorization locator binds the callback to the active
workspace member, platform and profile. The API verifies the returned account
against Zernio and checks token health before saving a connection. Reconnects
pin `reconnectAccountId`; callbacks cannot switch to a different account. The
API key stays server-side and only account/profile references are encrypted in
the connection record. New tables receive the same PostgreSQL tenant policies.

This release exposes two read operations: `zernio.account.get` and
`zernio.posts.list`. Post reads may be bounded or cached by Zernio; they are not
a complete-history export. Publishing, ads, comments and messages are not
advertised by these routes. Existing native routes retain their capabilities.

References: https://docs.zernio.com/multi-tenant,
https://docs.zernio.com/guides/connecting-accounts,
https://github.com/zernio-dev/zernio-dotnet/blob/main/docs/ConnectApi.md.
