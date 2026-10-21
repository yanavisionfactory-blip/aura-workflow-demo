# Content approval with Frame.io and PageProof

AURA can prepare a revision brief from Frame.io comments and an attached
PageProof comments export. This route keeps the two sources separate, retains
their asset/version identifiers, and waits for both inputs before drafting or
writing a reviewable brief. AURA does not edit an audiovisual asset or provide
Darius's final sign-off.

## Connect and select evidence

1. In **Connect → Find apps**, choose **Frame.io**. The direct connection uses
   Adobe consent for the official Frame.io V4 MCP service. Select the identity
   and organization containing the test asset. Existing broker connections are
   retained; the official route discovers its live schemas after consent.
2. Choose **PageProof** to read proof metadata through its official MCP service.
   PageProof documents that this connection excludes comment text and file
   imagery. It cannot replace the feedback input.
3. In PageProof, generate a comments print sheet for the chosen proof/version.
   Attach the PDF in AURA with **Attach docs**, and state the proof ID and version
   in the task. Searchable PDFs, UTF-8 text, CSV and JSON exports are supported;
   image-only, encrypted, empty and oversized exports stop with an explanation.
4. Supply the exact Frame.io asset/version. Ask AURA to read its comments and
   replies, import the attached PageProof comments, retain page/time references,
   flag conflicting requests, and prepare a revision brief **inside AURA**.
5. Review the brief. Any external comment or upload retains the normal action
   preview and approval. Supply a real revised file before re-review; a
   placeholder cannot satisfy that step. Read the actual version/status back
   from the provider, and leave final sign-off to the designated reviewer.

An import receipt identifies `input_mode=user_supplied_export` and
`vendor_api_called=false`; its SHA-256 and PDF page references identify the
retained source. The proof/version binding is supplied by the user, and the
receipt does not claim that the export is current or that the proof is approved.
An unreadable export or missing source is never recorded as an empty successful
review. Missing feedback, a mismatched source, implicit source fallbacks, and
writes that can run before successful feedback reads fail plan validation.

## Connection behavior and verification

The official endpoints are `https://mcp.frame.io/v1/mcp` and
`https://mcp.pageproof.com/mcp`. Public OAuth metadata is resolved only through
reviewed vendor domains. PKCE, resource binding, tenant membership and the
existing one-use callback checks remain required. Provider rejection of AURA's
client registration remains an explicit setup blocker. A public tools listing
alone is insufficient: an authenticated read probe must pass before a connection
is enabled. Frame.io's `mandatory_init` runs before the selected operation in
each new MCP session; writes and deletes retain consequential permissions.

Live metadata verification on 21 October 2026 found that Frame.io requires a
confidential registered client; its generated client secret stays encrypted on
the server. PageProof advertises one exact Azure-hosted issuer, OIDC discovery
and Client ID Metadata Documents instead of dynamic registration. AURA publishes
its secret-free client identity at `/v1/oauth/mcp-client/pageproof`, with the
configured callback URI. These flows retain PKCE and resource binding; other
Azure origins are not accepted. Provider metadata and client-setup compatibility
are separate from the user's consent and authenticated account verification.

Tests use mocked vendor boundaries to cover metadata discovery, domain rejection,
consent routing, authenticated probes and session initialization. They also
exercise the actual native import dispatch and plan validation. A live vendor
run still requires consented test accounts, authorized feedback, the selected
asset/version and a real revised file. Passing these tests does not establish
vendor authorization or a completed live workflow.

Vendor references:

- [Frame.io MCP](https://next.developer.frame.io/platform/docs/mcp/frame-io-mcp)
- [PageProof MCP and metadata limits](https://help.pageproof.com/en/articles/17274621-connect-pageproof-mcp-to-an-ai-assistant)
- [PageProof comments print sheet](https://help.pageproof.com/en/articles/417244-generating-a-print-sheet-of-comments)
