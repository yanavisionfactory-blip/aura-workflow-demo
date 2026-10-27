# PageProof registration investigation — 27 October 2026

Status: **not connected; no production fix deployed**.

This branch contains an isolated registration diagnostic. The production callback,
authentication configuration and application code have not been changed. The
`pageproof-client.json` file is a test identity, not the production client.

## Observed results

| Check | Result | Limit |
| --- | --- | --- |
| Fresh AURA Connect flow | PageProof returns `invalid_client` / `client is invalid` before sign-in; reference `p2cz0tv0n` | No user credentials or consent were reached |
| Production client document | HTTP 200, `application/json`; client ID equals document URL; exact callback present; public client with PKCE | Reachability from our environment does not prove PageProof fetched or accepted it |
| PageProof OIDC discovery | Advertises `client_id_metadata_document_supported: true` and token authentication method `none`; no `registration_endpoint` advertised | Advertisement alone does not prove custom clients are enabled |
| Independent metadata validation | Unmodified live production document accepted by local `oidc-provider@9.7.0`, including exact callback and authorization-code/refresh grants | Local compatibility test; PageProof's implementation and version are not established |
| Static AURA-owned test identity | Public raw GitHub document returns 200 and exact client ID; PageProof again returns `invalid_client`, reference `up8e0plhete` | Raw GitHub serves `text/plain`; this is corroborating evidence, not a definitive standards test |
| Production HTTP logs | The two client-document reads in the inspected window, at 15:23:02Z and 15:48:00Z, used our Python HTTP client | No observed provider retrieval; caching or earlier retrieval cannot be excluded |
| AURA regression tests | **87 passed** | Mocked-provider tests do not establish live consent, authenticated reads or refresh |

The static test used AURA's own callback, a test-only state, PKCE S256 and
`prompt=login`. It stopped at the provider error. No sign-in, consent, token
exchange, third-party client identity or production setting change was attempted.

## Production endpoints

- Application: https://yanavisionfactory-blip.github.io/aura-workflow-demo/
- Client metadata: https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/mcp-client/pageproof
- Callback: https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/mcp-agent/callback
- MCP: https://mcp.pageproof.com/mcp
- Discovered issuer: https://auth-server-prod-d9bwdmangffpf2es.westus-01.azurewebsites.net

## Interpretation and next supported step

No local metadata-format or callback mismatch was reproduced. The evidence points
to rejection of the client identity at PageProof, but does not establish their
internal cause. A hosting change did not resolve it.

AURA already supports a PageProof-issued registration through
`MCP_OAUTH_CLIENTS_JSON` (issuer, exact redirect URI and registered token
authentication method are validated). Production has no such registration set.

The next supported step is either acceptance of AURA's advertised metadata
document or registration details issued specifically for AURA. No self-service
registration procedure was found in PageProof's current public MCP instructions.
Do not invent a client ID, reuse another product's registration, or replace
OAuth with an extracted browser session.

After a valid registration is accepted, follow the live acceptance checks in
[the existing setup guide](../backend/docs/proofing-oauth-setup.md#acceptance-check).
Unit tests and a successful metadata fetch alone are not enough.

## Reproduce local regression checks

Source baseline: `4d6215b7083a1a259ff2926123027b54206eba27`.

From the repository root, install the backend dev dependencies in an isolated
Python 3.12 environment. Then run from `backend/`:

```sh
python -m pytest tests/test_proofing_connections.py tests/test_mcp_registered_clients.py tests/test_mcp_oauth.py -q
```

Result on 27 October 2026: 87 passed, 173 deprecation warnings, 4.78 seconds.
Warnings concern FastAPI lifecycle handlers and SQLAlchemy datetime defaults.

The local independent validator supplied the public document unchanged to
`oidc-provider@9.7.0` with client metadata support enabled, then checked
`Client.find(client_id)`, `redirectUriAllowed`, `grantTypeAllowed` and
`tokenEndpointAuthMethod`. Its network fetch was replaced with the saved document;
it did not authenticate against PageProof.

## References

- [PageProof's official MCP connection instructions](https://help.pageproof.com/en/articles/17274621-connect-pageproof-mcp-to-an-ai-assistant)
- [OAuth Client ID Metadata Document draft](https://www.ietf.org/archive/id/draft-ietf-oauth-client-id-metadata-document-00.html)
- [oidc-provider source](https://github.com/panva/node-oidc-provider)

A support follow-up was sent on 27 October in the existing PageProof thread.
This investigation did not send an additional message.
