// Browser-agent tools only. This module renders no controls, does not export
// auth tokens/cookies and is inert in browsers without WebMCP (including Safari).
const OPERATION = "frameio.assistant.browser_review";
const uuid = { type: "string", pattern: "^[0-9a-fA-F-]{36}$" };
const target = { account_id: uuid, project_id: uuid, file_id: uuid };
const schema = (properties, required = Object.keys(properties)) => ({
  type: "object", properties, required, additionalProperties: false,
});

export function frameioBrowserToolDefinitions(api) {
  const onlyReview = async (runId) => {
    const run = await api.getRun(runId);
    if (run.plan?.steps?.length !== 1 || run.plan.steps[0].operation !== OPERATION) {
      throw new Error("This tool can only operate a single-step native Frame.io browser review.");
    }
    return run;
  };
  const tools = [
    {
      name: "aura_frameio_prepare_review",
      description: "Prepare an AURA workflow using Frame.io's native AI Assistant. Call only after visibly confirming the exact asset and accessible AI Assistant in an authenticated Frame.io tab. AURA verifies the file through its existing connection, then binds an attended browser executor. This does not start analysis. Keep the agent active; never export browser cookies or credentials.",
      inputSchema: schema({ ...target, instructions: { type: "string", minLength: 20, maxLength: 6000 }, request_key: { type: "string", minLength: 1, maxLength: 150 } }),
      execute: async ({ instructions, request_key, ...selected }) => {
        const connection = await api.request("/v1/frameio-browser/connect", { method: "POST", body: JSON.stringify(selected) });
        const run = await api.createRun(`Use Frame.io's own AI Assistant through an attended browser executor.\n\n${instructions}`,
          null, request_key, { frameio_browser_review: { ...selected, instructions, browser_session_id: connection.browser_session_id } });
        return { ...connection, run_id: run.id, status: run.status,
          next: "Read the AURA plan before approval; then start, poll for the exact invocation prompt, submit it unchanged to native Frame.io AI Assistant and return its fresh response." };
      },
    },
    {
      name: "aura_frameio_review_status",
      description: "Read the saved AURA plan, execution status and native review result for this workflow. Planning may still be in progress. Do not interpret a prepared plan as a completed review.",
      inputSchema: schema({ run_id: uuid }),
      execute: ({ run_id }) => api.getRun(run_id),
      annotations: { readOnlyHint: true },
    },
    {
      name: "aura_frameio_start_review",
      description: "Approve and start the reviewed single-step Frame.io native-assistant workflow in AURA. Requires the user's instruction to run this review. This queues a job for the active browser agent; it does not invoke an alternative model.",
      inputSchema: schema({ run_id: uuid }),
      execute: async ({ run_id }) => {
        await onlyReview(run_id);
        const readiness = await api.request(`/v1/runs/${run_id}/preflight`, { method: "POST" });
        if (!readiness.passed) return { state: "blocked", readiness };
        return api.approveRun(run_id, null, false, { reviewToolOutputs: false, executeReviewedPlan: false, reviewBetweenTools: false });
      },
    },
    {
      name: "aura_frameio_claim_review",
      description: "Claim or poll this AURA run's native Frame.io review job and renew the attended executor lease. Use only the returned exact target and unique prompt. Submit that prompt once in Frame.io AI Assistant, wait for its new completed response, and record fresh user/assistant message IDs plus the visible native video-analysis events. Never reuse an old conversation response.",
      inputSchema: schema({ browser_session_id: uuid, run_id: uuid }),
      execute: ({ browser_session_id, run_id }) => api.request(`/v1/frameio-browser/${browser_session_id}/runs/${run_id}/poll`, { method: "POST" }),
    },
    {
      name: "aura_frameio_complete_review",
      description: "Return the actual fresh Frame.io AI Assistant response to its claimed AURA workflow. Copy the original response faithfully, including limitations. Supply only evidence observed in that exact conversation after this invocation's unique prompt. Do not manufacture native analysis events, timestamps, coverage or audio success. This saves browser-agent evidence, not a vendor API receipt.",
      inputSchema: schema({
        browser_session_id: uuid, invocation_id: uuid,
        request_hash: { type: "string", pattern: "^[a-f0-9]{64}$" },
        source_url: { type: "string", maxLength: 500 },
        user_message_id: { type: "string", minLength: 1, maxLength: 200 },
        assistant_message_id: { type: "string", minLength: 1, maxLength: 200 },
        submitted_prompt: { type: "string", minLength: 20, maxLength: 10000 },
        response_markdown: { type: "string", minLength: 80, maxLength: 100000 },
        analysis_events: { type: "array", items: { type: "string", maxLength: 2000 }, minItems: 1, maxItems: 20 },
        audio_status: { type: "string", enum: ["reviewed", "unassessed", "absent"] },
        limitations: { type: "array", items: { type: "string", maxLength: 2000 }, minItems: 1, maxItems: 30 },
      }),
      execute: ({ browser_session_id, ...receipt }) => api.request(`/v1/frameio-browser/${browser_session_id}/complete`, { method: "POST", body: JSON.stringify(receipt) }),
    },
  ];
  return tools.map(tool => ({ ...tool, execute: async input => {
    try { return await tool.execute(input); }
    catch (error) { return { isError: true, error: error.message || "Frame.io browser review failed." }; }
  } }));
}

export function registerFrameioBrowserTools(context, api) {
  if (!context?.registerTool) return () => {};
  const controller = new AbortController();
  const names = [];
  for (const tool of frameioBrowserToolDefinitions(api)) {
    try {
      const registration = context.registerTool(tool, { signal: controller.signal });
      names.push(tool.name);
      if (registration?.catch) registration.catch(() => {});
    } catch { /* Browser API preview variations must not break AURA. */ }
  }
  return () => {
    controller.abort();
    // Compatibility with the earlier navigator.modelContext implementation.
    if (context.unregisterTool) for (const name of names) {
      try { context.unregisterTool(name); } catch { /* Already unregistered. */ }
    }
  };
}
