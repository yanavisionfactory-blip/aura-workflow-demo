# Frame.io and PageProof OAuth setup

The customer connects through AURA's normal provider consent flow. Client
registration is an AURA operator responsibility. A provider rejection before
sign-in is not an end-user password problem.

## Observed production blockers (26 October 2026)

- Frame.io MCP rejected dynamic registration with HTTP 400:
  `One or more redirect URIs are not allowed.`
- PageProof's authorization page rejected AURA with `invalid_client` (reference
  `mqmym5oduhe`). Its discovery document advertises client metadata documents.
  AURA's public document responds with HTTP 200 and its callback matches, but
  that does not prove PageProof fetched or accepted it.
- Neither flow reached account consent. Neither connection is verified.

Application: https://yanavisionfactory-blip.github.io/aura-workflow-demo/

Exact production callback for both providers:

```text
https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/mcp-agent/callback
```

PageProof public client identity:

```text
https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/mcp-client/pageproof
```

## Supported correction

Ask the provider to accept AURA's existing registration mechanism, or obtain
client registration details issued specifically for AURA by the **MCP
authorization server** advertised by that provider. A general Adobe API app,
another AI product's client ID, and a legacy Frame.io connector are not
interchangeable with this registration. Do not change callbacks to another
product's domain or disable provider validation.

For a provider-issued registration, set the backend secret
`MCP_OAUTH_CLIENTS_JSON`. It defaults to `{}` and only supports keys `frame-io`
and `pageproof`. Each configured entry must contain:

| Field | Required value |
| --- | --- |
| `client_id` | The provider-issued AURA client ID |
| `issuer` | The exact authorization server identified by MCP discovery |
| `redirect_uri` | AURA's exact registered HTTPS callback above |
| `token_endpoint_auth_method` | The registered method: `none`, `client_secret_post`, or `client_secret_basic` |
| `client_secret` | Required for either secret method; omitted or empty for `none` |

Store this only in the API's server environment, never GitHub Pages/VITE
configuration or source control. Preserve existing entries when adding a
provider. Do not create fake IDs or secrets. Updating the deployment environment's
`RAILWAY_TOKEN` does not register an OAuth client.

AURA prefers the configured registration over CIMD/dynamic registration. It
checks the discovered issuer, exact callback and advertised authentication
method before producing a consent URL. An invalid configured registration does
not silently fall back to a different client. Existing grants cannot silently
migrate to another client. Credentials are encrypted with the existing vault;
public responses and the PageProof metadata document contain no client secret.

## Acceptance check

1. Start a fresh Connect session; do not reuse an expired OAuth link.
2. Complete provider sign-in and consent for the intended account/team.
3. Require AURA's authenticated live probe and enabled connection. A public
   tools catalog, successful metadata fetch or unit test is insufficient.
4. Perform one scoped read and verify refresh before calling the integration
   production-ready. Frame.io must initialize the session and read the chosen
   asset/version. PageProof must return team metadata; comments still require
   the explicit export described in `docs/content-approval.md`.

The configured-client path is implemented and regression tested. Provider
registration, real consent, authenticated reads and refresh remain unverified
until actual AURA registrations are supplied and accepted.

Protocol reference: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration

## Prepared provider requests (not sent)

### Frame.io

Destination: `support@frame.io`, listed at
https://help.frame.io/en/articles/9092154-frame-io-support

Subject: AURA MCP integration: callback registration rejected before consent

Hello Frame.io Support,

We are connecting AURA to the official Frame.io V4 MCP at
`https://mcp.frame.io/v1/mcp`. Client registration returns HTTP 400:
`One or more redirect URIs are not allowed.` The request uses an authorization
code flow, PKCE S256 and `application_type=web`.

Application: https://yanavisionfactory-blip.github.io/aura-workflow-demo/

Requested callback:
`https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/mcp-agent/callback`

Could you approve this AURA callback or tell us the supported process for
registering a custom MCP client? If a pre-registered client is required, please
provide its setup process, issuer and token authentication method, with a secure
way to provision any client secret. We have implemented issuer-bound registered
client support in AURA. We have not reached account sign-in or consent.

Thank you.

### PageProof

Destination: PageProof's in-app support chat, described at
https://help.pageproof.com/en/

Subject: AURA MCP integration: invalid_client using advertised client metadata

Hello PageProof Support,

We are connecting AURA to `https://mcp.pageproof.com/mcp`. Your advertised
authorization server supports `client_id_metadata_document_supported=true`,
but authorization returns `invalid_client` / `client is invalid` before sign-in.
The error reference from 26 October 2026 is `mqmym5oduhe`.

Application: https://yanavisionfactory-blip.github.io/aura-workflow-demo/

Client metadata URL:
`https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/mcp-client/pageproof`

Registered callback in that document:
`https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/mcp-agent/callback`

The document is public, returns HTTP 200 JSON, and its client ID equals its URL.
It declares a web client, authorization code flow, the exact callback and token
authentication method `none`. AURA uses PKCE S256.

Could you identify why this client is rejected and whether AURA requires approval
or pre-registration? If pre-registration is required, please provide the setup
process and a secure way to provision any credentials. We understand PageProof
MCP exposes metadata and does not expose proof imagery or comment text.

Thank you.
