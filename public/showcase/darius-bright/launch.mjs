export const auraUrl = 'https://yanavisionfactory-blip.github.io/aura-workflow-demo/';
export function normalizeAssetUrl(value) {
  try {
    const url = new URL(value.trim());
    const uuid = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
    const match = url.pathname.match(new RegExp(`^/project/(${uuid})/view/(${uuid})/?$`));
    if (url.protocol !== 'https:' || !['app.frame.io', 'next.frame.io'].includes(url.hostname) || url.username || url.password || url.port || !match) return null;
    return `https://app.frame.io/project/${match[1].toLowerCase()}/view/${match[2].toLowerCase()}`;
  } catch { return null; }
}
export function launchRequest(asset, prompt) {
  const target = normalizeAssetUrl(asset);
  return `Run a NEW video review through AURA using Frame.io's own AI Assistant, in MY accounts.

AURA: ${auraUrl}
Frame.io asset: ${target || '[Paste my exact Frame.io asset URL here before running]'}

Review instructions:
${prompt.trim()}

I authorize preparing, approving and running this read-only video review in my AURA workspace. Do not post comments or send notifications.

Use an active browser agent. Confirm my signed-in AURA workspace, connected Frame.io account, exact video and accessible native AI Assistant. Do not use Yana's account, an old run, or any saved demo response. If login is needed, let me sign in securely.

On the authenticated AURA tab, discover its WebMCP tools. Call aura_frameio_prepare_review_from_link with my asset_url, the review instructions and a new unique request_key. Inspect the plan with aura_frameio_review_status: it must contain only frameio.assistant.browser_review. Call aura_frameio_start_review, then aura_frameio_claim_review with the returned browser_session_id and run_id.

Submit the exact unique claimed prompt to Frame.io's native AI Assistant on the verified video. Wait for its fresh answer and observed native video-analysis events; keep the executor active and renew the claim as needed. Return the original response, actual message IDs, observed events, audio status and limitations through aura_frameio_complete_review. Confirm the AURA run completed using aura_frameio_review_status, and give me its result link.

Never substitute AURA Intelligence or another model for Frame.io AI Assistant. Do not invent a native response, audio review or full-video coverage. If browser tools, AURA WebMCP or native AI Assistant are unavailable, stop before starting. Identify the exact failed check, explain how to reopen a browser-capable session or reconnect the account, and preserve the asset and instructions for retry. If a run was already started, report its actual run ID and status; check status before retrying to avoid duplicate runs. Never report completion until the saved result is verified. The saved demo is an example, not the output of this new run.`;
}
