# Frame.io native AI Assistant availability

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
assistant requests stop before model planning with a capability-unavailable
message. Previously saved native-assistant plans fail readiness and direct
execution without opening a browser or offering reconnect. They never fall back
to another analysis engine.

The existing Frame.io OAuth connection, asset/comment operations, and separately
labelled Frame.io + AURA Intelligence video operation remain available. Using
that analysis engine requires a request that permits it; it is not Frame.io's
own assistant.

The retired session/invocation database models and tenant policies remain for
record retention. This withdrawal does not delete stored records or alter the
existing OAuth connection. Browser-worker restart closes its temporary sessions.
