import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  PROCESS_CHANGED_EVENT,
  processStatusLabel,
  processTriggerLabel,
} from "../src/lib/processes.mjs";

test("process summaries distinguish manual, event, and scheduled starts", () => {
  assert.equal(processTriggerLabel({ trigger: { type: "manual" } }), "Started manually");
  assert.equal(
    processTriggerLabel({ trigger: { type: "event", event_type: "deal.closed" } }),
    "When deal.closed",
  );
  assert.equal(
    processTriggerLabel({ trigger: { type: "schedule", cadence: "daily", local_time: "08:00" } }),
    "Daily at 08:00",
  );
  assert.equal(processStatusLabel("waiting_event"), "Waiting for event");
  assert.equal(PROCESS_CHANGED_EVENT, "aura:process-changed");
});

test("process creation lives in workflow history instead of the result page", () => {
  const results = readFileSync(
    new URL("../src/components/aura/ResultsView.jsx", import.meta.url),
    "utf8",
  );
  const history = readFileSync(
    new URL("../src/components/aura/HistoryPanel.jsx", import.meta.url),
    "utf8",
  );
  assert.match(results, /Schedule/);
  assert.match(results, /New workflow/);
  assert.match(results, /<ScheduleModal/);
  assert.doesNotMatch(results, /Create process/);
  assert.doesNotMatch(results, /<ProcessModal/);
  assert.match(history, /> Workflows/);
  assert.match(history, /> Processes/);
  assert.match(history, /<ProcessPanel/);
  assert.match(history, /Build a process/);
  assert.match(history, /selectionMode={selectingProcess}/);
  assert.match(history, /<ProcessModal/);
});

test("the process builder orders selected runs and captures operational policy", () => {
  const modal = readFileSync(
    new URL("../src/components/aura/ProcessModal.jsx", import.meta.url),
    "utf8",
  );
  assert.match(modal, /getPythonRun/);
  assert.match(modal, /source_run_id/);
  assert.match(modal, /DragDropContext/);
  assert.match(modal, /AURA-proposed context/);
  assert.match(modal, /context_instructions/);
  assert.match(modal, /failure_policy/);
  assert.match(modal, /manual/);
  assert.match(modal, /event/);
  assert.match(modal, /schedule/);
  assert.match(modal, /what is allowed/);
});

test("process cases expose operational controls without replacing workflow history", () => {
  const panel = readFileSync(
    new URL("../src/components/aura/ProcessPanel.jsx", import.meta.url),
    "utf8",
  );
  assert.match(panel, /Start a case/);
  assert.match(panel, /> Pause/);
  assert.match(panel, /> Resume/);
  assert.match(panel, /> Stop/);
  assert.match(panel, /> Edit/);
  assert.match(panel, /listProcessInstances/);
  assert.match(panel, /updateProcessInstance/);
});
