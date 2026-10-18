import assert from "node:assert/strict";
import test from "node:test";
import { savedRunResults } from "../src/lib/savedRunResults.mjs";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";

const report = {
  step_id: "step-1", step_key: "review", tool: "aura", operation: "report.compose",
  critic: { action: "accept" }, outcome_check: { status: "verified" },
  provider_result: { title: "Fictional client review", status: "draft", synthetic: true,
    summary: "Synthetic marketing review", body: "**FICTIONAL CLIENT — SYNTHETIC DEMO DATA**\n\n## Performance\n| Leads | 120 |",
    sources: [{ id: "S1", title: "Synthetic outcomes", content: "120 leads; 55 bookings; 20 customers" }] },
};

test("AURA-native reports retain full body and sources after reopening saved history", () => {
  const result = savedRunResults({ id: "run-1", status: "completed",
    plan: { name: "Review" }, result: { outputs: [report],
      result_presentation: { primary_step_key: "review" },
      unified_deliverable: { summary: "Completed", deliverable: "A short summary" } } });
  assert.equal(result.primaryResult.kind, "report");
  assert.equal(result.primaryResult.provider, "AURA");
  assert.equal(result.primaryResult.preview.body, report.provider_result.body);
  assert.deepEqual(result.primaryResult.preview.sources, report.provider_result.sources);
  assert.equal(result.primaryResult.link, null);
  assert.match(result.summary, /synthetic/);
});

test("unverified reports cannot masquerade as completed saved artifacts", () => {
  const result = primaryResultFromOutputs([{ ...report, critic: { action: "escalate" } }]);
  assert.notEqual(result.kind, "report");
});
