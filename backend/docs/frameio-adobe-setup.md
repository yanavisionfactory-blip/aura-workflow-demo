# Frame.io V4 through Adobe OAuth

This is a separate, read-only native API connection. Adobe Developer Console
credentials must never be used as Frame.io MCP broker credentials. Existing MCP
connections keep their own grants and callback.

## Operator registration

In Adobe Developer Console, add **Frame.io API → User Authentication → OAuth →
OAuth Web App** to the AURA project. For the current production backend use:

* Default redirect URI:
  `https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/frameio/callback`
* Redirect URI pattern (literal periods escaped, no wildcard):
  `https://impartial-emotion-production-49d4\.up\.railway\.app/v1/oauth/frameio/callback`
* Scopes: `openid,email,profile,offline_access,additional_info.roles`.

Register only the callback for the target environment. If a deployment needs a
different host, configure `OAUTH_CALLBACK_OVERRIDES` and register that exact URI
in the same Adobe app. Do not broaden the redirect pattern.

Save the issued client ID and secret as `FRAMEIO_CLIENT_ID` and
`FRAMEIO_CLIENT_SECRET` in the API and worker's server configuration. Never put
them in source control, public frontend variables, OAuth links, or support mail.
The client secret uses a redacting settings type. End-user tokens remain in
AURA's encrypted credential vault.

## Connection and verification

The native Frame.io route is disabled until both app credentials are configured.
New connections then prefer this route; they never fall through to Nango or the
MCP broker if native setup is missing. The OAuth flow uses Adobe IMS
`/ims/authorize/v2` and `/ims/token/v3`, with confidential-client Basic auth for
token exchange and refresh. Signed workspace state and exact callback matching
use AURA's existing native OAuth contract.

The callback requires a refresh token, a successful `/v4/me` read, and at least
one accessible account from `/v4/accounts` before saving a verified connection.
An Adobe sign-in alone is not proof of a Frame.io subscription or membership.
Record a live connection test and refresh test before claiming completion.

Exposed operations are `frameio.identity.get`, `frameio.accounts.list`,
`frameio.file.get`, and `frameio.comments.list`. They are GET-only. File and
comment reads require exact Frame.io account/file UUIDs. Adobe aliases and
version-stack IDs are not accepted as a substitute for a selected file version.
The comments operation verifies the file and follows all pages (up to 1,000 root
comments), includes replies, and fails on incomplete or inconsistent coverage.
Pagination cannot change host or resource. Attachment metadata is preserved,
but attachment content is not read. Comment completion never means asset
approval. PageProof still needs its separate connection and comments export.

## Source contracts

* https://developer.frame.io/platform/v4/docs/quick-start
* https://developer.frame.io/platform/v4/docs/guides/authentication/python-sdk
* https://developer.frame.io/platform/v4/api-reference/accounts/index
* https://developer.frame.io/platform/v4/api-reference/files/show
* https://developer.frame.io/platform/v4/api-reference/comments/index

## Provisioning checklist

Code deployment does not create Adobe credentials or connect an account. Record
the app registration, server configuration, successful account authorization,
and live API/refresh verification separately before claiming the connection works.
