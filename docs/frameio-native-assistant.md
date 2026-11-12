# Frame.io native AI Assistant through AURA

`frameio.assistant.review` submits an exact Frame.io video version and the approved
review instructions to Frame.io's in-product AI Assistant using an authenticated
AURA browser session. It returns that assistant's actual response into the existing
AURA report view. `frameio.video.review` remains the separate Frame.io-source +
AURA Intelligence operation. Explicit native-assistant requests cannot silently
fall back to that operation or a different analysis engine.

## Connection and execution

1. Keep the existing Frame.io OAuth connection. AURA uses it to verify the exact
   account, file version and project before opening or submitting anything.
2. In the workflow's existing account checks, select **Connect Frame.io AI
   Assistant**. The separate connection page opens an AURA-owned browser. Sign in
   to the same Frame.io account, complete any identity verification, and check
   access. AI Assistant must already be enabled for the account.
3. Return to the workflow, check readiness again, and start the approved review.
   AURA submits the instructions once, waits for a new completed reply with a
   native video-analysis completion event, and saves its response and receipt.

There is no public native-assistant API dependency and no use of an external
client's private cookies. Sign-in sessions are memory-only, tenant and connection
bound, restricted to their creator for interactive access, and expire after two
hours or any browser-worker restart. Workspace admins create these sessions.
Disconnect closes the browser. Password/input payloads are not stored in AURA's
database; screenshots and input responses use `Cache-Control: no-store`.

The browser worker must run a single replica (as the existing production worker
does). It exposes authenticated `/v1/frameio-assistant` routes using the existing
worker token. `INTERACTIVE_BROWSER_CONCURRENCY` bounds active sign-in sessions.

## Evidence and failure behavior

The response carries `analysis_provider: frameio_ai_assistant`, the source
account/file IDs, invocation ID, native message ID, input hash and actual response.
It does not invent model identity, sampled-frame coverage or audio success.
Frame.io's limitations and uncertain timestamps remain in the report.

Submission intent is committed to the tenant database before the browser click.
Retries poll the same invocation and never submit it again. If the worker restarts
or acknowledgement is lost before a job can be found, AURA stops with an uncertain
state rather than starting a duplicate review. Inspect the Frame.io conversation
before intentionally creating a new workflow run.

This is a browser adapter: vendor UI changes, sign-in challenges, unavailable AI
entitlement or an assistant reply without completed video analysis stop execution.
AURA does not automatically solve identity challenges or select another engine.
The review prompt prohibits comments, notifications, asset changes and unrelated
work; the adapter only operates the native assistant composer and reads its reply.

Tests cover tenant/owner isolation, exact target binding, new-message correlation,
submission recovery without duplication, readiness, engine substitution rejection,
result presentation and preservation of audio limitations. A live native review
still requires the user's separate Frame.io sign-in in AURA.
