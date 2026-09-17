import assert from "node:assert/strict";
import test from "node:test";

import {
  editedArgumentsForStep,
  mergeLegacyPreviewIntoArguments,
  resolvedApprovalStep,
  setArgumentAtPath,
  validateReviewArguments,
} from "../src/lib/approvalReview.mjs";

test("runtime review contracts preserve exact editable arguments", () => {
  const step = resolvedApprovalStep(
    { tool: "Canva", title: "Create the presentation", riskLevel: "modify" },
    {
      consequential: true,
      operation: "canva.presentation.create",
      approval_id: "approval-1",
      approval_status: "pending",
      approval_preview: {
        status: "ready",
        arguments: { title: "Plan", phases: [{ period: "Q1", title: "Launch", items: ["Ship"] }] },
        review_contract: { version: 1, kind: "presentation", title: "Review presentation", fields: [] },
      },
    },
    "Canva",
  );

  assert.equal(step.reviewContract.kind, "presentation");
  assert.deepEqual(editedArgumentsForStep(step), {
    title: "Plan",
    phases: [{ period: "Q1", title: "Launch", items: ["Ship"] }],
  });
});

test("unknown actions get a generic editable contract instead of a read-only list", () => {
  const step = resolvedApprovalStep(
    { tool: "Custom", title: "Create object" },
    {
      consequential: true,
      operation: "custom.object.create",
      approval_id: "approval-2",
      approval_status: "pending",
      approval_preview: { status: "ready", arguments: { name: "First", payload: { score: 1 } } },
    },
    "Custom",
  );

  assert.deepEqual(step.reviewContract.editable_paths, [["name"], ["payload"]]);
  assert.deepEqual(setArgumentAtPath(step.resolvedArguments, ["payload", "score"], 2), {
    name: "First",
    payload: { score: 2 },
  });
});

test("legacy rich email edits are converted back into executable arguments", () => {
  const step = { resolvedArguments: { to: "old@example.com", attachments: [{ name: "deck.pdf" }] } };
  const edited = mergeLegacyPreviewIntoArguments(step, {
    type: "email",
    to: "new@example.com",
    subject: "Updated",
    body: "Hello",
  });

  assert.deepEqual(edited, {
    to: "new@example.com",
    subject: "Updated",
    body: "Hello",
    attachments: [{ name: "deck.pdf" }],
  });
});

test("rich structured previews cannot approve incomplete nested values", () => {
  const contract = {
    fields: [{
      key: "phases",
      path: ["phases"],
      type: "array",
      required: true,
      min_items: 1,
      item_schema: {
        type: "object",
        required: ["period", "title", "items"],
        properties: {
          period: { type: "string", minLength: 1 },
          title: { type: "string", minLength: 1 },
          items: { type: "array", minItems: 1, items: { type: "string", minLength: 1 } },
        },
      },
    }],
  };

  assert.equal(validateReviewArguments(contract, { phases: [] }).length, 1);
  assert.equal(validateReviewArguments(contract, { phases: [{ period: "", title: "Launch", items: [""] }] }).length, 2);
  assert.deepEqual(validateReviewArguments(contract, { phases: [{ period: "Q1", title: "Launch", items: ["Ship"] }] }), []);
});
