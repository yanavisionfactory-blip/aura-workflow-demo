import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  schedulePayload,
  schedulesForWorkflow,
  scheduleSummary,
} from "../src/lib/workflowSchedule.mjs";

test("schedule payload binds a completed backend run and the browser timezone", () => {
  assert.deepEqual(schedulePayload({
    backendRunId: "run-1",
    historyWorkflowId: "history-1",
    title: "Weekly report",
    cadence: "weekly",
    dayOfWeek: 1,
    dayOfMonth: 15,
    time: "08:30",
    approvalMode: "writes",
    notifyCompleted: true,
    notifyAttention: false,
    timezone: "Europe/Berlin",
  }), {
    source_run_id: "run-1",
    history_workflow_id: "history-1",
    name: "Weekly report",
    cadence: "weekly",
    timezone: "Europe/Berlin",
    local_time: "08:30",
    day_of_week: 1,
    day_of_month: null,
    approval_mode: "writes",
    notify_on_completion: true,
    notify_on_attention: false,
  });
});

test("schedules map to durable history ids before falling back to prompts", () => {
  const schedules = [
    { id: "a", history_workflow_id: "history-1", workflow_prompt: "different" },
    { id: "b", history_workflow_id: null, workflow_prompt: "Run report" },
  ];
  assert.deepEqual(
    schedulesForWorkflow(schedules, { id: "history-1", prompt: "Run report" }).map((item) => item.id),
    ["a", "b"]
  );
});

test("schedule summary describes the durable calendar rule", () => {
  assert.equal(
    scheduleSummary({ cadence: "weekly", day_of_week: 1, local_time: "08:00" }),
    "Every Monday at 08:00"
  );
});

test("the results modal saves to the durable scheduler and history manages it", () => {
  const modal = readFileSync(new URL("../src/components/aura/ScheduleModal.jsx", import.meta.url), "utf8");
  const history = readFileSync(new URL("../src/components/aura/HistoryPanel.jsx", import.meta.url), "utf8");
  const detail = readFileSync(new URL("../src/components/aura/WorkflowDetail.jsx", import.meta.url), "utf8");
  assert.match(modal, /createWorkflowSchedule/);
  assert.doesNotMatch(modal, /entities\.Schedule/);
  assert.match(history, /listWorkflowSchedules/);
  assert.match(history, /updateWorkflowSchedule/);
  assert.match(detail, /Pause/);
  assert.match(detail, /Remove/);
});
