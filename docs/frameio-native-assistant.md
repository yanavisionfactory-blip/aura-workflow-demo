# Frame.io native AI Assistant availability

## Attended browser workflow

`frameio.assistant.browser_review` connects an approved AURA workflow to a
browser agent that is already signed into Frame.io and can see its native AI
Assistant. It is distinct from the withdrawn remote-login adapter below.
It does not export cookies or expose a remote browser-control URL.

The existing AURA page registers five WebMCP tools when the host browser supports
that API: prepare, read status, approve/start, claim/poll, and return the native
response. The page renders no additional controls. Safari remains unchanged.
The browser agent observes the Frame.io UI; it is not an analysis engine.

Preparation verifies the exact account/project/file using AURA's existing
Frame.io OAuth connection. Start uses normal plan approval and readiness.
Execution creates a durable invocation with a unique prompt and request hash.
The owning agent submits that exact prompt, observes a new completed reply and
native video-analysis event, then returns the original response and limitations.
The AURA worker saves it as a normal tool result labelled Frame.io AI Assistant.

Sessions are scoped to workspace, approving user, connection and exact video.
The agent's explicit polls renew a fifteen-minute session lease. Invocations
expire after ten minutes. Cancelled or changed runs, wrong users/assets/prompts,
and reused response IDs are rejected. The old remote sign-in endpoints remain
absent. There is no substitute-model fallback.

This requires an active attended browser agent (for example, the current ChatGPT
session). It does not wake ChatGPT automatically, remotely control an iPhone,
or enable unattended scheduled runs. Completion is browser-agent evidence,
not a cryptographically verified Frame.io API receipt; audio access and precise
timing limitations from Frame.io must be retained. AURA verifies workflow
delivery, not the correctness or completeness of every media observation.

## Withdrawn remote-login adapter

The experimental browser adapter and separate sign-in UI were withdrawn. They
required a second, short-lived browser session and did not provide a working
connection through the existing Frame.io authorization. The former connection
URL redirects to AURA's existing workflow page. No new sign-in page is shown.

Frame.io's official documentation distinguishes its MCP from its in-product AI
Assistant and lists visual-content understanding as unavailable through MCP:
https://help.frame.io/en/articles/17218043-connecting-frame-io-mcp-server-with-ai-clients-beta

The documented MCP tools do not expose a call to the native assistant:
https://developer.frame.io/platform/docs/mcp/frame-io-mcp

`frameio.assistant.review` is no longer advertised or executable. Explicit native
assistant requests without a browser-review binding stop before model planning
with a capability-unavailable message. Previously saved native-assistant plans fail readiness and direct
execution without opening a browser or offering reconnect. They never fall back
to another analysis engine.

The existing Frame.io OAuth connection, asset/comment operations, and separately
labelled Frame.io + AURA Intelligence video operation remain available. Using
that analysis engine requires a request that permits it; it is not Frame.io's
own assistant.

The retired session/invocation database models and tenant policies remain for
record retention. This withdrawal does not delete stored records or alter the
existing OAuth connection. Browser-worker restart closes its temporary sessions.
