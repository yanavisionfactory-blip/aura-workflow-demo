import test from "node:test";
import assert from "node:assert/strict";
import { frameioBrowserToolDefinitions, registerFrameioBrowserTools } from "../src/lib/frameioBrowserTools.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";

test("browsers without WebMCP remain unchanged", () => {
  const cleanup = registerFrameioBrowserTools(undefined, {});
  cleanup();
});

test("native assistant response keeps its engine attribution and limitations in the existing report view", () => {
  const body = "00:22 — Correct the circuit-directory font. Audio could not be assessed.";
  const output = { operation: "frameio.assistant.browser_review", step_key: "review",
    critic: { action: "accept" }, outcome_check: { status: "verified" },
    provider_result: { body, title: "Frame.io review", status: "draft", analysis_provider: "frameio_ai_assistant" } };
  const result = primaryResultFromOutputs([output], {}, { primary_step_key: "review" });
  assert.equal(result.kind, "report");
  assert.equal(result.provider, "Frame.io AI Assistant");
  assert.equal(result.preview.body, body);
});

test("native review preparation preserves prompt and exact verified browser binding", async () => {
  const calls = [];
  const api = {
    request: async (path, options) => { calls.push([path, options]); return { browser_session_id: "binding", execution_mode: "attended_browser_agent" }; },
    createRun: async (...args) => { calls.push(args); return { id: "run", status: "queued" }; },
  };
  const tool = frameioBrowserToolDefinitions(api).find(tool => tool.name === "aura_frameio_prepare_review");
  const result = await tool.execute({ account_id: "account", project_id: "project", file_id: "file", instructions: "Review the video carefully.", request_key: "one" });
  assert.equal(result.run_id, "run");
  assert.equal(calls[1][3].frameio_browser_review.instructions, "Review the video carefully.");
  assert.equal(calls[1][3].frameio_browser_review.browser_session_id, "binding");
  assert.equal(calls.length, 2);
});

test("start tool cannot approve another model or an unrelated workflow", async () => {
  let approvals = 0;
  const api = { getRun: async () => ({ plan: { steps: [{ operation: "frameio.video.review" }] } }), approveRun: async () => { approvals++; } };
  const result = await frameioBrowserToolDefinitions(api).find(tool => tool.name === "aura_frameio_start_review").execute({ run_id: "run" });
  assert.equal(result.isError, true);
  assert.equal(approvals, 0);
});

test("blocked readiness never starts a native review", async () => {
  let approvals = 0;
  const api = { getRun: async () => ({ plan: { steps: [{ operation: "frameio.assistant.browser_review" }] } }), request: async () => ({ passed: false }), approveRun: async () => { approvals++; } };
  const result = await frameioBrowserToolDefinitions(api).find(tool => tool.name === "aura_frameio_start_review").execute({ run_id: "run" });
  assert.equal(result.state, "blocked");
  assert.equal(approvals, 0);
});

test("browser tool cleanup unregisters only its own registrations", () => {
  const names = [], removed = [];
  let signal;
  const cleanup = registerFrameioBrowserTools({ registerTool(tool, options) { names.push(tool.name); signal = options.signal; }, unregisterTool(name) { removed.push(name); } }, {});
  assert.equal(names.length, 5);
  cleanup();
  assert.equal(signal.aborted, true);
  assert.deepEqual(removed, names);
});
