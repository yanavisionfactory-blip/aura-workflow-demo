import test from "node:test";
import assert from "node:assert/strict";
import { articleMarkdown, articleWordCount, jiraDocument, jiraText } from "../src/lib/actionContent.mjs";
import { operationStepTitle, removeStepInstruction } from "../src/lib/planPresentation.mjs";

test("article review shows complete readable prose and keeps active provider markup out", () => {
  const html = '<h2>Homeowner guide</h2><p>Check <strong>airflow</strong> &amp; filters.</p><script>alert("private")</script><a href="javascript:alert(1)">Unsafe link</a>';
  const text = articleMarkdown(html);
  assert.match(text, /## Homeowner guide/);
  assert.match(text, /Check \*\*airflow\*\* & filters/);
  assert.doesNotMatch(text, /<|script|javascript|private/);
  assert.equal(articleWordCount('<p>Read <a href="https://example.org">this guide</a> today.</p>'), 4);
});

test("Jira handoff review round trips prose rather than serialized transport", () => {
  const document = jiraDocument("Saved draft links\nRankings: not measured");
  assert.equal(jiraText(JSON.stringify(document)), "Saved draft links\nRankings: not measured\n");
  assert.equal(jiraText("Existing prose"), "Existing prose");
});

test("readbacks cannot be labelled as content writes by incidental approval wording", () => {
  assert.equal(operationStepTitle({ operation: "wordpress-org.search-posts", reason: "Verify saved post after approved write" }), "Verify the saved articles");
  assert.equal(operationStepTitle({ operation: "rankmath.post_seo.get", reason: "Verify the draft content after approval" }), "Verify saved SEO settings");
  assert.match(removeStepInstruction({ action: "Draft the content" }, 5), /^Remove step 6/);
  assert.notEqual(removeStepInstruction({ action: "Draft the content" }, 4), removeStepInstruction({ action: "Draft the content" }, 5));
});
