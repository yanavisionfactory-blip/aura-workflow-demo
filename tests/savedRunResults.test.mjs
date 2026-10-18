import test from "node:test";
import assert from "node:assert/strict";
import { savedRunResults } from "../src/lib/savedRunResults.mjs";

test("reopened results retain saved synthesis and don't wait for new suggestions", () => {
  const result = savedRunResults({ status: "completed", plan: { name: "Agency SEO" }, result: {
    unified_deliverable: { summary: "Three drafts were saved.", deliverable: "Saved content and remaining checks.", next_steps: ["Review the drafts"] },
    outputs: [],
  } });
  assert.equal(result.status, "completed");
  assert.equal(result.summary, "Three drafts were saved.");
  assert.equal(result.outcomes[0].detail, "Saved content and remaining checks.");
  assert.equal(result.suggestionsLoading, false);
});

test("a partial run preserves completed receipts without claiming workflow completion", () => {
  const run = { status: "waiting_for_action", plan: { name: "Agency SEO" }, steps: [{ id: "saved", key: "articles", status: "completed", operation: "wordpress-org.update-post", output: {
    critic: { action: "accept" }, outcome_check: { status: "verified" }, resolved_arguments: { post: 108 },
    provider_result: { id: 108, status: "draft", title: { raw: "Plano guide" }, content: { raw: "<p>Complete saved article.</p>" } },
  } }, { status: "failed", operation: "rankmath.get", output: { provider_result: { error: "unavailable" } } }] };
  const before = JSON.stringify(run);
  const result = savedRunResults(run);
  assert.equal(result.status, "needs_attention");
  assert.match(result.title, /incomplete/);
  assert.match(result.summary, /has not completed/);
  assert.equal(result.primaryResult.articles[0].body, "Complete saved article.");
  assert.deepEqual(result.metrics, []);
  assert.equal(JSON.stringify(run), before);
});
