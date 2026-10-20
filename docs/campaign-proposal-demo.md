# Unpublished campaign proposal demonstration

The campaign preparation outcome is a sourced proposal and implementation handoff.
It does not require creating an advertising campaign. Never present a saved report,
a connection test, or an external assistant's tool call as native AURA execution.

## Connect Meta research to AURA

Open the app with `?connect=supermetrics`. It opens the connection form with the
reviewed `https://mcp.supermetrics.com/mcp` endpoint prefilled. Nothing connects
until the user clicks the connection button and completes the provider's consent.
Choose the Supermetrics team that already contains the authorized Meta account.

The separate ChatGPT Supermetrics connection does not transfer its OAuth tokens
to AURA. AURA registers its own public OAuth client with PKCE and stores its own
encrypted credentials. Existing Meta permissions and data-source connections may
be reused by Supermetrics; do not request Meta credentials in chat or export tokens.

This route requests read/research scopes only. Its discovered catalog excludes
campaign writes, dashboards, creative uploads, invitations and support messages.
Business-context retrieval requires `action: get`. A newly authenticated MCP
connection is enabled only after its live research tools have been discovered.
An account-list response establishes access to the returned account, not a client's
relationship to it. Empty Page/pixel lists establish only what this connection
returned, not the nonexistence of assets elsewhere.

Sources for the connection implementation:
- https://github.com/supermetrics-public/supermetrics-mcp
- https://mcp.supermetrics.com/.well-known/oauth-protected-resource
- https://api.supermetrics.com/.well-known/oauth-authorization-server

## Agency presentation sequence

Task links may use `?prompt=` with URL-encoded plain text (up to 20,000 characters).
They prefill the existing command input only. Opening a link does not create a run,
call a provider, select an account, approve a plan, or change connection permissions.
The user starts planning through the normal **Create plan** control and reviews the
compiled plan before execution. **Run again** and suggested next actions from a saved
result retain the task text. A new intent cannot be replaced by a late restore of
an earlier run.

1. Show the saved, unpublished Classic Roofing proposal and review tracker.
2. Open AURA's saved Google Ads keyword-research receipt. Explain that the returned
   account is a research account until the client's actual account is verified.
3. After AURA's own Supermetrics consent succeeds, run the account-check prompt
   below. Inspect the plan before running: every operation must be read-only.
4. Show returned account identities, Page/measurement visibility and the Columbia
   city catalog entry. An empty result is an honest access finding.
5. Show the sourced ad concepts, asset checklist and pending approvals. Keep all
   publication and account-write actions out of the plan.
6. End with the implementation handoff. Client asset access and human approval
   remain visible requirements; a personal account is not relabelled as the client.

## Account-check prompt

Replace the two bracketed fields with an account ID returned by discovery and the
existing proposal's Google Doc ID. Do not invent identifiers.

```text
Prepare unpublished account-check evidence for the Classic Roofing campaign proposal.
Use the connected Supermetrics research agent. Discover the Facebook Ads data source
FA and verify its authentication. Discover accessible advertiser accounts, then read
saved business context for the selected account [VERIFIED META ACCOUNT ID] using
action get. Read its Pages and conversion definitions/pixels. Search the targeting
catalog for Columbia with type city and select the US / South Carolina city result.
Preserve exact returned IDs and distinguish empty lists from unavailable operations.
Read the existing proposal using Google Docs document ID [EXISTING PROPOSAL DOC ID].
Return a sourced account-check result with the provider evidence and manual handoffs.
Keep this run limited to account checks and research. No campaign, post, conversion
event, creative upload, publication, account-setting change or spend is authorized.
```

## Client-controlled implementation requirements

- Verify the client business/ad-account relationship and authorized managed Page.
- Review channel fit, service-area coverage, CTA mapping and usage rights.
- Approve measurement and perform destination/inquiry-path QA during implementation.
- Confirm budget, currency, bidding, dates and named reviewers before launch.
- Include GBP or indoor screens only after choosing their scope and verified tools;
  do not imply those optional channels ran in the core PPC preparation task.

Unit tests and public metadata checks prove software behavior and endpoint identity.
They do not prove a completed AURA customer OAuth callback, advertiser read, permission
grant or client asset access. Capture those separate run receipts after authorization.
