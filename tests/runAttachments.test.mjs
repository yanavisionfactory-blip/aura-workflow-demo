import assert from "node:assert/strict";
import test from "node:test";
import { attachedDocumentsFromRun } from "../src/lib/runAttachments.mjs";
import { alternativeRecoveryPrompt } from "../src/lib/runRecovery.mjs";

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

