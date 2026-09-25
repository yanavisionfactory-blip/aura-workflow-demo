import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  backendRunNeedsSync,
  backendRunHistoryProjection,
  historyStatusForBackendRun,
  isExecutedBackendRun,
  upsertHistoryRecord,
  workflowForBackendRun,
  workflowRollup,
} from "../src/lib/workflowHistory.mjs";

const backendRun = {
  id: "backend-run-1",
  status: "completed",
  plan_approved: true,
  prompt: "Create tomorrow's forecast presentation",
  created_at: "2026-09-14T17:00:00Z",
  updated_at: "2026-09-14T17:00:12Z",
  plan: {
    name: "Create forecast presentation",
    interpretation: "Create tomorrow's forecast presentation in Canva",
    steps: [{
      tool_slug: "canva",
      operation: "design.create",
      reason: "create the populated forecast presentation",
      expected_output: "Canva presentation",
      consequential: true,
    }],
  },
  result: {
    completed_steps: 1,
    unified_deliverable: { summary: "Created the forecast presentation." },
  },
};

test("only approved backend executions enter My workflows", () => {
  assert.equal(isExecutedBackendRun(backendRun), true);
  assert.equal(isExecutedBackendRun({ ...backendRun, plan_approved: false }), false);
  assert.equal(isExecutedBackendRun({ ...backendRun, id: "" }), false);
});

test("backend executions become reusable workflow and history records", () => {
  const projection = backendRunHistoryProjection(backendRun);
  assert.equal(projection.workflow.name, "Create forecast presentation");
  assert.equal(projection.workflow.last_run_status, "completed");
  assert.equal(projection.run.backend_run_id, "backend-run-1");
  assert.equal(projection.run.duration_seconds, 12);
  assert.deepEqual(projection.run.metrics, [{ value: "1", label: "step completed" }]);
  assert.equal(projection.run.steps[0].tool, "Canva");
  assert.equal(projection.run.steps[0].riskLevel, "modify");
});

test("running and unsuccessful backend states map to panel statuses", () => {
  assert.equal(historyStatusForBackendRun({ status: "awaiting_approval" }), "running");
  assert.equal(historyStatusForBackendRun({ status: "recovering" }), "running");
  assert.equal(historyStatusForBackendRun({ status: "failed" }), "failed");
  assert.equal(historyStatusForBackendRun({ status: "cancelled" }), "failed");
});

test("reruns prefer their explicit saved workflow before prompt matching", () => {
  const workflows = [
    { id: "prompt-match", prompt: backendRun.prompt },
    { id: "saved-workflow", prompt: "Earlier wording" },
  ];
  const match = workflowForBackendRun({
    ...backendRun,
    inputs: { saved_workflow_id: "saved-workflow" },
  }, workflows);
  assert.equal(match.id, "saved-workflow");
});

test("workflow rollups are derived from saved run records without double counting", () => {
  const rollup = workflowRollup("workflow-1", [
    { workflow_id: "workflow-1", status: "completed", summary: "Older", backend_updated_at: "2026-09-14T10:00:00Z" },
    { workflow_id: "workflow-1", status: "failed", summary: "Latest", backend_updated_at: "2026-09-14T11:00:00Z", steps: [{ tool: "Canva" }] },
    { workflow_id: "other", status: "completed", backend_updated_at: "2026-09-14T12:00:00Z" },
  ]);
  assert.equal(rollup.run_count, 2);
  assert.equal(rollup.last_run_status, "failed");
  assert.equal(rollup.last_summary, "Latest");
  assert.deepEqual(rollup.steps, [{ tool: "Canva" }]);
});

test("unchanged backend history is not written again", () => {
  const projected = backendRunHistoryProjection(backendRun).run;
  assert.equal(backendRunNeedsSync({ ...projected, id: "saved-run" }, projected), false);
  assert.equal(backendRunNeedsSync({ ...projected, status: "running" }, projected), true);
  assert.equal(backendRunNeedsSync(null, projected), true);
});

test("live history updates replace existing records without duplication", () => {
  const records = [{ id: "run-1", status: "running" }];
  assert.deepEqual(upsertHistoryRecord(records, { id: "run-1", status: "completed" }), [
    { id: "run-1", status: "completed" },
  ]);
  assert.deepEqual(upsertHistoryRecord(records, { id: "run-2", status: "running" }).map((run) => run.id), [
    "run-2",
    "run-1",
  ]);
});

test("execution and the My workflows panel are wired to durable history", () => {
  const demo = readFileSync(new URL("../src/pages/Demo.jsx", import.meta.url), "utf8");
  const history = readFileSync(
    new URL("../src/components/aura/HistoryPanel.jsx", import.meta.url),
    "utf8",
  );

  assert.equal(demo.includes("const ensureSavedWorkflowRun = async"), true);
  assert.equal(demo.includes("await ensureSavedWorkflowRun()"), false);
  assert.equal(demo.includes("void ensureSavedWorkflowRun().catch"), true);
  assert.ok(demo.indexOf("await approvePythonPlan(runId, reviewedPlan.steps, false)")
    < demo.indexOf("void ensureSavedWorkflowRun().catch"));
  assert.equal(demo.includes("startPythonPreparation"), false);
  assert.equal(demo.includes("createPythonRunResilient(planningPrompt, null"), true);
  assert.equal(demo.includes("backend_run_id: backendRunId"), true);
  assert.equal(history.includes("listPythonRuns({ limit: 100 })"), true);
  assert.equal(history.includes("run.backend_run_id === backendRun.id"), true);
  assert.equal(history.indexOf("setLoading(false)") < history.indexOf("reconcileDurableHistory(saved.workflows"), true);
  assert.equal(history.includes("WORKFLOW_HISTORY_CHANGED_EVENT"), true);
  assert.equal(history.includes('import { aura } from "@/api/auraClient"'), true);
  assert.equal(history.includes("base44.entities"), false);
});

test("workflow detail edits use the durable AURA data client", () => {
  for (const file of ["WorkflowDetail.jsx", "HistoryRunDetail.jsx"]) {
    const source = readFileSync(
      new URL(`../src/components/aura/${file}`, import.meta.url),
      "utf8",
    );
    assert.equal(source.includes('import { aura } from "@/api/auraClient"'), true, file);
    assert.equal(source.includes("base44.entities"), false, file);
  }
});
