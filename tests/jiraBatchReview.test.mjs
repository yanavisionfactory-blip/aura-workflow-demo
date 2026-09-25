import assert from "node:assert/strict";
import test from "node:test";

import { editJiraBatchTask, jiraBatchTasks, removeJiraBatchTask } from "../src/lib/jiraBatchReview.mjs";
import { plannedApprovalStep, requiresPreparedJiraReview, resolvedApprovalStep } from "../src/lib/approvalReview.mjs";
import { jiraReceiptTasks } from "../src/lib/jiraReceipt.mjs";
import { primaryResultFromOutputs, resultMetrics } from "../src/lib/resultPresentation.mjs";

const block = (type, parts) => ({
  type,
  [type]: { rich_text: parts.map((plain_text) => ({ plain_text })) },
});

test("Jira batch review shows only the titles the connector will create", () => {
  const args = {
    source_blocks: [
      block("paragraph", ["This is background, not a task"]),
      block("to_do", ["  Call ", " the customer  "]),
      block("bulleted_list_item", ["Ship the draft"]),
      block("numbered_list_item", ["Call the customer"]),
    ],
    max_issues: 2,
  };
  assert.deepEqual(jiraBatchTasks(args), [
    { index: 1, title: "Call the customer" },
    { index: 2, title: "Ship the draft" },
  ]);
  assert.equal(jiraBatchTasks({ source_blocks: "{{steps.notes.results}}" }).length, 0);
  assert.equal(jiraBatchTasks({ source_blocks: args.source_blocks, max_issues: 1 }).length, 1);
});

test("editing and removing a Jira task changes the arguments sent for approval", () => {
  const args = { project_key: "AURA", source_blocks: [block("to_do", ["Original"]), block("to_do", ["Second"])] };
  const edited = editJiraBatchTask(args, 0, "Revised task");
  assert.deepEqual(jiraBatchTasks(edited).map((task) => task.title), ["Revised task", "Second"]);
  assert.equal(args.source_blocks[0].to_do.rich_text[0].plain_text, "Original");
  assert.deepEqual(jiraBatchTasks(removeJiraBatchTask(edited, 1)).map((task) => task.title), ["Revised task"]);
  assert.equal(edited.project_key, "AURA");
});

test("batch Jira approval has its own preview before and after reading Notion", () => {
  const pending = plannedApprovalStep(
    { tool: "Jira", riskLevel: "modify" },
    { operation: "jira.issues.create_from_blocks", consequential: true, arguments: { source_blocks: "{{steps.notes.results}}" } },
    "Jira",
  );
  assert.equal(pending.preview.type, "jira_batch");
  const resolved = resolvedApprovalStep(pending, {
    operation: "jira.issues.create_from_blocks", consequential: true,
    approval_status: "pending", approval_preview: {
      status: "ready", arguments: { source_blocks: [block("to_do", ["Send summary"])], max_issues: 20 },
      review_contract: { kind: "ticket", operation: "jira.issues.create_from_blocks", fields: [] },
    },
  }, "Jira");
  assert.equal(resolved.preview.type, "jira_batch");
  assert.deepEqual(jiraBatchTasks(resolved.resolvedArguments).map((task) => task.title), ["Send summary"]);
});

test("Jira batch waits for real Notion tasks before approving any write", () => {
  assert.equal(requiresPreparedJiraReview([
    { operation: "notion.search" }, { operation: "jira.issues.create_from_blocks" },
  ]), true);
  assert.equal(requiresPreparedJiraReview([{ operation: "jira.issue.get" }]), false);
});

test("saved Jira receipt shows actual task names and safe links during and after verification", () => {
  const receipt = {
    issues: [{ key: "AURA-21" }, { key: "AURA-22" }],
    requested_summaries: ["Write brief", "Invite team"],
    result_url: "https://example.atlassian.net/browse/AURA-21",
  };
  const tasks = jiraReceiptTasks(receipt);
  assert.deepEqual(tasks.map((task) => task.title), ["Write brief", "Invite team"]);
  assert.equal(tasks[1].url, "https://example.atlassian.net/browse/AURA-22");
  const output = { step_key: "create_jira_tasks", operation: "jira.issues.create_from_blocks", provider_result: receipt };
  const primary = primaryResultFromOutputs([output], {}, { primary_step_key: "create_jira_tasks" });
  assert.equal(primary.kind, "jira_tasks");
  assert.deepEqual(primary.tasks, tasks);
  assert.deepEqual(resultMetrics([], [{ status: "completed", output }]), [
    { value: "2", label: "Jira tasks created" },
  ]);
  assert.equal(jiraReceiptTasks({ ...receipt, result_url: "javascript:alert(1)" })[0].url, null);
});
