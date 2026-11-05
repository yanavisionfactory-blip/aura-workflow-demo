# Reporting syncs and provider quota

A saved OAuth connection proves authorization, not unlimited reporting capacity.
Do not reconnect an account or substitute synthetic metrics when a provider
returns a quota error.

## Runtime behavior

For an authorized read, HTTP 429 is a durable retry condition. Pipedream's
HTTP-200 action envelopes are inspected as well: Google Ads
`RESOURCE_EXHAUSTED` is treated as 429 even when its wrapper omits HTTP status.
Only numeric retry metadata escapes the provider boundary. AURA preserves
`Retry-After` seconds/HTTP dates and Google's `retryDelay` protobuf duration,
including the JSON string inside an action error.

The failed read stops immediately, retaining its next allowed attempt time.
The existing durable supervisor resets only that read's attempt cycle and queues
the same approved step after the provider deadline. It does not reconnect,
revise the query, change accounts, or use a fallback to evade quota. An early
worker delivery preserves a future dispatch and does not call the provider.
Completed receipts and the approved plan are retained. Existing recovery limits
remain in force; persistent quota exhaustion eventually requires an operator.
Writes with uncertain outcomes are never automatically replayed by this path.

The same scheduler handles native HTTP 429 responses, including Mailchimp,
broker action errors, and HTTP rate limits from MCP transports. Provider-specific
errors that do not expose HTTP 429 need separate, verified mappings; this change
does not claim that every Meta/MCP textual error is a recognized quota signal.

## Google Ads capacity configuration

As of November 5, 2026, Google's migration guide states that developer tokens
were sunset September 9, 2026. API access and quotas are attached to the Google
Cloud project that owns the OAuth credentials. Some older Google summary pages
still describe developer tokens; follow the migration guide's current body.

For the Google Ads connection in AURA, identify the OAuth client configured in
the Pipedream project, then the Google Cloud project that owns it. Inspect that
project's Google Ads API access level and usage. Request an appropriate access
level/quota increase there, or have the connector operator resolve its capacity.
Do not create replacement projects or rotate identities to bypass a limit.
Changing only a legacy developer-token header cannot raise the current quota.
Never copy credentials or raw provider errors into issues, logs, or prompts.

Sources:
- https://developers.google.com/google-ads/api/docs/api-policy/developer-token
- https://developers.google.com/google-ads/api/docs/access-levels
- https://pipedream.com/docs/connect/api-proxy
- https://mailchimp.com/developer/marketing/api-concepts/rate-limits-and-timeouts/

## Other connections

Meta Ads uses the separate Pipeboard read-only MCP authorization described in
`meta-ads-connection.md`; Facebook Pages authorization is not Ads access.
Mailchimp uses its own OAuth account and data-center routing. Check these
providers independently. Passing connection verification is not proof that a
particular campaign report has completed.

Regression coverage includes a wrapped 16-hour Google delay, ordinary/native
429 responses, malformed retry metadata, one-call throttling at the broker,
durable scheduling, duplicate delivery before the deadline, and resumption of
the same read after quota becomes available. These are automated tests, not
claims about live advertising outcomes.
