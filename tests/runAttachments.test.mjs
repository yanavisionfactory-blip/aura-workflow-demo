import assert from "node:assert/strict";
import test from "node:test";
import { attachedDocumentsFromRun, uploadedVideoRecovery } from "../src/lib/runAttachments.mjs";
import { alternativeRecoveryPrompt, recoveryForRun } from "../src/lib/runRecovery.mjs";

const video = { name: "original.mp4", file_url: "data:video/mp4;base64,b3JpZ2luYWw=", size: 8 };

test("recovery retains the exact uploaded video separately from prompt text", () => {
  const run = { prompt: "Review this video from beginning to end", inputs: { attached_documents: [video] } };
  const restored = attachedDocumentsFromRun(run);
  assert.deepEqual(restored, [video]);
  assert.notEqual(restored[0], video);
  assert.ok(!alternativeRecoveryPrompt(run).includes(video.file_url));
  restored[0].name = "edited.mp4";
  assert.equal(video.name, "original.mp4");
});

test("legacy document inputs work and explicit empty attachments stay empty", () => {
  assert.deepEqual(attachedDocumentsFromRun({ inputs: { documents: [video] } }), [video]);
  assert.deepEqual(attachedDocumentsFromRun({ inputs: { attached_documents: [], documents: [video] } }), []);
  assert.deepEqual(attachedDocumentsFromRun({}), []);
  assert.deepEqual(attachedDocumentsFromRun({ inputs: { attached_documents: {} } }), []);
});

test("restoration copies only attachment metadata and never invents external references", () => {
  const run = { inputs: { attached_documents: [null, {},
    { name: "remote.mp4", file_url: "https://example.test/video.mp4" },
    { ...video, unrelated: "private", provider_result: { token: "private" } },
  ] } };
  assert.deepEqual(attachedDocumentsFromRun(run), [video]);
});

const failedVideo = () => ({ status: "waiting_for_action", plan_approved: true,
  prompt: "Review this video from beginning to end with timestamped feedback.",
  inputs: { attached_documents: [video] },
  blocker: { code: "resource_selection_required", action: "choose_resource" },
  steps: [{ id: "identity", operation: "frameio.identity.get", status: "completed", consequential: false },
    { id: "review", operation: "frameio.video.review", status: "failed", consequential: false,
      error: "[invalid_request] Select the exact Frame.io file UUID.", output: {} }],
});

test("a legacy local target failure offers the exact saved upload in a new plan", () => {
  const run = failedVideo();
  const before = JSON.stringify(run);
  assert.deepEqual(uploadedVideoRecovery(run).document, video);
  const recovery = recoveryForRun(run);
  assert.equal(recovery.alternativeLabel, "Review uploaded video");
  assert.equal(recovery.canRetry, false);
  assert.equal(recovery.stepId, "review");
  assert.match(recovery.fix, /original.mp4/);
  assert.equal(alternativeRecoveryPrompt(run), run.prompt);
  assert.match(alternativeRecoveryPrompt(run, "Use another source"), /Use another source/);
  assert.equal(JSON.stringify(run), before);
});

test("saved execution evidence enables upload recovery when the displayed error is generic", () => {
  const run = failedVideo();
  run.steps[1].error = "AURA couldn't complete this step safely after automatic recovery. Try again or adjust the workflow.";
  assert.equal(uploadedVideoRecovery(run), null);
  run.steps[1].recovery = { phase: "after_dispatch", reason_code: "frameio_target_invalid" };
  assert.equal(recoveryForRun(run).alternativeLabel, "Review uploaded video");
  assert.equal(alternativeRecoveryPrompt(run), run.prompt);
  assert.deepEqual(attachedDocumentsFromRun(run), [video]);
  run.blocker.action = "reconnect_account";
  assert.equal(uploadedVideoRecovery(run), null);
});

test("a diagnosed invalid target without a single upload asks for a source instead of another failed plan", () => {
  for (const documents of [[], [video, { ...video, name: "other.mp4" }]]) {
    const run = failedVideo();
    run.inputs.attached_documents = documents;
    run.steps[1].error = "The execution error was sanitized.";
    run.steps[1].recovery = { reason_code: "frameio_target_invalid" };
    const recovery = recoveryForRun(run);
    assert.equal(recovery.needsVideoSource, true);
    assert.equal(recovery.alternativeLabel, "Select video for review");
    assert.equal(recovery.canRetry, false);
    assert.equal(recovery.canSkip, false);
    assert.match(recovery.fix, /original instructions/);
  }
});

test("upload recovery never guesses missing sources or replays existing effects", () => {
  const changes = [
    (r) => { r.inputs = {}; },
    (r) => { r.inputs.attached_documents = [video, { ...video, name: "other.mp4" }]; },
    (r) => { r.steps[1].output.provider_result = { body: "Saved review" }; },
    (r) => { r.steps[1].consequential = true; },
    (r) => { delete r.steps[0].consequential; },
    (r) => { r.steps[1].error = "Provider timed out"; },
    (r) => { r.blocker.action = "reconnect_account"; },
    (r) => { r.status = "completed"; },
    (r) => { r.plan_approved = false; },
  ];
  for (const change of changes) {
    const run = failedVideo(); change(run);
    assert.equal(uploadedVideoRecovery(run), null);
  }
});

