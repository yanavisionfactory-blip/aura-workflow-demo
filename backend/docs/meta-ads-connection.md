# Meta Ads authorization and reporting

AURA supports an operator-owned [direct Meta connection](meta-direct-setup.md)
and the existing Pipeboard route. Direct Meta becomes the preferred new connection
only after its server-side app credentials are configured. Existing Pipeboard
accounts keep their own credentials and executable contracts.

The **Pipeboard** route opens Pipeboard's hosted OAuth flow. Its card explicitly
identifies Pipeboard. Facebook Pages remains a separate
connection and never satisfies Meta Ads reporting requirements.

The route uses the provider's published protected-resource and authorization
metadata at `https://meta-ads.mcp.pipeboard.co/`, public-client registration,
PKCE S256, resource binding, and AURA's existing encrypted credential vault.
Only `mcp:read` is requested. The two reviewed query-bearing registration and
authorization URLs retain `platform=meta-ads`; arbitrary query parameters and
other origins are rejected. Refresh uses the existing managed MCP token flow.

The user signs into Pipeboard and authorizes their Meta account through the
provider flow. This does not automatically grant access to another client's
ad account: Meta must already give that user permission to the intended account.
A successful OAuth callback must also return a valid authenticated ad-account
list before AURA enables the connection. An empty account list proves the
connection works but does not prove access to Elias's account.

AURA only exposes reviewed account, campaign, ad-set, ad, and Insights read tools.
Writes, deletes, unknown tools, aliased tool names, and caller-supplied credentials
are excluded. Actual schemas are discovered after consent; a public tools list
alone is never treated as verified account access. Campaign reports still need
an explicit account choice, date range, and separate Google Ads and GA4 access.

The managed-agent wrapper reapplies Meta's reviewed policy after adding agent
metadata. Its generic write-approval default must not relabel the account-read
probe, or a valid OAuth grant cannot reach authenticated account verification.
Regression tests exercise the complete discovery and verification path for both
supported tool-name formats while checking that writes and credential overrides
remain unavailable.

On 2026-10-26, Meta's first-party MCP dynamic-registration endpoint rejected
AURA with `invalid_client_metadata` / `Dynamic registration is not available for
this client.` No client identity was spoofed and no provider review was bypassed.
Pipeboard accepted registration for AURA's actual HTTPS callback (HTTP 201).
That registration check is setup evidence, not evidence of user consent or
access to an advertising account. Provider plans and Meta permissions may impose
additional account-specific limits at sign-in.
