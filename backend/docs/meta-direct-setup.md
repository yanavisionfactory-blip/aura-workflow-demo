# Direct Meta Ads reporting

AURA now has a native `meta-ads-direct` connection using AURA's own Meta app and
Facebook Login. The separate `meta-ads-mcp` route and saved Pipeboard grants are
not migrated or removed. Configuring another Meta app is an operator task, never
an end-user API-key form.

## Meta app setup

1. In Meta for Developers, create or select the AURA app owned by the appropriate
   business portfolio and add the Marketing API reporting use case and Facebook
   Login. For Facebook Login for Business, use a configuration requesting only
   `ads_read`; set its configuration ID below if the app requires it.
2. Register this exact production **Valid OAuth Redirect URI**:
   `https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/meta-ads-direct/callback`
   Keep web OAuth login enabled and use HTTPS. For another environment, use its
   own exact `PUBLIC_URL` callback or an explicit `OAUTH_CALLBACK_OVERRIDES` entry.
   Do not register the frontend or Pipeboard callback for this direct route.
3. Configure the app's accurate privacy policy and data-deletion instructions
   and complete Meta's business/app verification and permission review applicable
   to customer accounts. Request `ads_read` for reporting; this connector does
   not require `ads_management`. Confirm the app's permission access and live
   mode before asking unrelated customer accounts to connect. Development-mode
   authorization by an app tester is not evidence of public customer availability.
4. Set `META_CLIENT_ID` and `META_CLIENT_SECRET` securely in the API and worker
   environment, and in any canary environment used for direct-connection tests.
   Keep them out of source, chat, screenshots, OAuth links and all `VITE_` values.
   Optional: `META_LOGIN_CONFIG_ID`. `META_GRAPH_API_VERSION` defaults to `v26.0`;
   version upgrades require retesting the read contracts.
5. Deploy/restart the affected services through the reviewed main-branch release
   process. The catalog prefers **Connect directly with Meta** only when both
   server-side app credentials are present. Missing setup never silently switches
   an explicit direct connection request to a broker.

Meta app registration, its approvals and an individual's ad-account permissions
are separate requirements. Code deployment alone does not satisfy them.

## Authorization and renewal

Starting consent requires an authenticated AURA workspace member. The signed
state is stored as a hash with the initiating member and a ten-minute expiry,
and consumed atomically before exchanging a code. Replayed, unissued, cross-route
or expired state and removed workspace memberships are rejected. The table is
covered by the same workspace row-level security as saved connections.

The server exchanges the code using its app secret and exact callback, exchanges
the short token for a long-lived user token, and checks `/me`, `/me/permissions`
and the complete `/me/adaccounts` list. `ads_read` must be granted and at least
one ad account must be returned before credentials and read capabilities are
saved. Tokens are encrypted by the existing vault; the app secret is redacted
by Settings. No credential is supplied in a plan or returned to the browser.

Facebook Login's long-lived user token is not a refresh-token grant. AURA saves
and checks Meta's expiry; expiration or revocation requires a new authorization.
Network/rate-limit failures remain retryable and are not labelled expired
consent. Failed consent or verification preserves any existing connection.
Outgoing API requests use a bearer header and `appsecret_proof`; HTTPX and API
access logs omit URL query strings. Provider error messages/bodies are not logged
or exposed as connection diagnostics.

## Reporting contract

The read-only operations are `meta-ads.identity.get`, `meta-ads.accounts.list`,
`meta-ads.campaigns.list`, `meta-ads.adsets.list`, `meta-ads.ads.list`, and
`meta-ads.insights.get`. There are no campaign writes, arbitrary Graph endpoints,
user-selected fields, batches or credential overrides.

Inventory reads explicitly request every supported effective status, including
paused, archived and deleted objects, without a date filter. Saved receipts retain
that status coverage; provider retention still applies. Campaign inventory is
distinct from a dated performance report. Discovery records the actual
`ads_read` and `business_management` grant status. Missing business discovery
permission does not imply that campaign reporting on a listed account failed,
and an empty result does not prove a permissions problem. Ordinary reconnect
continues to request only `ads_read`; broader business access requires separate
authorization, never a silent scope expansion.

The user must explicitly select an account from the account list. Every account
read verifies that exact numeric account ID. Insights require full ISO dates
including year, return one all-days result for the inclusive period, and accept
account/campaign/ad-set/ad level. Reads preserve raw provider values, account
currency/timezone, attribution settings, query dates and retrieval time. Action
values/types stay separate; reach is not summed. No rows is an empty result,
not fabricated zero performance. Compare unequal periods with their day counts
and appropriate daily rates rather than treating raw totals as equal durations.

Pagination is cursor-only on the same code-owned Graph resource, bounded to
5,000 rows/50 pages and a total timeout. Provider `next` URLs and their tokens
are never fetched or returned. Incomplete pages, duplicate object/insight rows,
wrong account IDs or out-of-period insights fail the read instead of reporting
partial data as complete. Large reports must be split into smaller date ranges
or supplied as a complete export. No asynchronous report jobs are created.

For campaign reports, retrieve each comparison period separately, save the real
source rows, then use the report tool's required saved-input/readback flow.
Existing source approval, Google Sheets authorization and report checks still
apply; this connector never manufactures an approved export or bypasses them.

## Verification before enabling a customer

Automated tests exercise authorization, state replay/expiry/tenant membership,
permission failures, encrypted persistence, fixed-host requests, pagination,
expiry, provider failures, catalog preference and the full planning path.
They use controlled HTTP responses and do not prove a live Meta app is approved.

After app configuration, an authorized tester should connect directly, confirm
the intended account appears, explicitly select it, and read a small known date
range. Compare returned currency, timezone, attribution and metrics against Ads
Manager with the same settings. Record the live test separately. Elias must
complete his own Meta consent; another user's successful test does not connect
his AURA workspace.

## Provider references

- https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/
- https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/
- https://developers.facebook.com/docs/permissions/reference/ads_read/
- https://developers.facebook.com/docs/marketing-api/overview/authorization/
- https://developers.facebook.com/docs/marketing-api/insights/
- https://github.com/meta/facebook-python-business-sdk/blob/main/facebook_business/adobjects/adaccount.py
- https://github.com/meta/facebook-python-business-sdk/blob/main/facebook_business/session.py
