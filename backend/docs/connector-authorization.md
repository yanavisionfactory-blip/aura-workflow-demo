# Connector authorization operations

Connection setup belongs to the shared backend, not an individual workflow.
Connect and reconnect requests run a fresh preflight, bounded to ten seconds,
before a user authorization session is issued. Healthy connected workflow steps
do not perform this extra configuration read.

## Configuration ownership

Existing OAuth integration credentials belong to Nango. Backend environment
credentials are used only to provision a missing integration. Updating environment
variables does not repair an existing Nango integration. Never automatically
overwrite an existing integration's client ID or secret: that can invalidate
refresh tokens for every connected account.

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
