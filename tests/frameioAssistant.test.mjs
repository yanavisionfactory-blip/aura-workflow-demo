import assert from "node:assert/strict";
import test from "node:test";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";
import { videoReviewPlanContent } from "../src/lib/planPresentation.mjs";
import { operationProviderName } from "../src/lib/providerDisplay.mjs";

test("native Frame.io assistant report keeps its actual engine and audio limitations", () => {
  const body = "| Timestamp | Issue | Correction |\n| --- | --- | --- |\n| 00:22 | Font mismatch | Correct label |\n\nAudio could not be accessed and remains unassessed.";
  const outputs = [
    { step_key: "file", operation: "frameio.file.get", critic: { action: "accept" }, outcome_check: { status: "verified" }, provider_result: { source_provider: "frameio", file: { id: "asset", type: "file" } } },
    { step_key: "review", operation: "frameio.assistant.review", critic: { action: "accept" }, outcome_check: { status: "verified" }, provider_result: { status: "draft", synthetic: false, title: "Native review", analysis_provider: "frameio_ai_assistant", body } },
  ];
  const result = primaryResultFromOutputs(outputs);
  assert.equal(result.kind, "report");
  assert.equal(result.provider, "Frame.io AI Assistant");
  assert.equal(result.preview.body, body);
  assert.equal(operationProviderName("frameio", "frameio.assistant.review"), "Frame.io AI Assistant");
  assert.equal(operationProviderName("frameio", "frameio.video.review"), "Frame.io + AURA Intelligence");
  assert.match(videoReviewPlanContent({ operation: "frameio.assistant.review" }).iWill, /own AI Assistant/);
});
