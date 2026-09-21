import assert from "node:assert/strict";
import test from "node:test";

import {
  editedArgumentsForStep,
  fallbackReviewContract,
  hasUnresolvedWorkflowReference,
  mergeLegacyPreviewIntoArguments,
  plannedApprovalStep,
  requiresActionPreview,
  resolvedApprovalStep,
  setArgumentAtPath,
  validateReviewArguments,
} from "../src/lib/approvalReview.mjs";

test("every planned consequential action gets the appropriate review renderer", () => {
  const cases = [
    ["gmail.send", { to: "me", subject: "Forecast", body: "Sunny" }, "email"],
    ["canva.presentation.create", { title: "Forecast", phases: [] }, "presentation"],
    ["jira.issue.create", { project_key: "AURA", summary: "Review" }, "ticket"],
    ["report.document.create", { title: "Brief", body: "Complete brief" }, "document"],
    ["custom.object.create", { name: "Object" }, "action"],
  ];

  for (const [operation, args, kind] of cases) {
    const step = plannedApprovalStep(
      { tool: "App", title: operation, riskLevel: "modify" },
      { operation, arguments: args, consequential: true },
      "App",
    );
    assert.equal(step.reviewContract.kind, kind);
    assert.equal(step.reviewContract.operation, operation);
    assert.deepEqual(step.resolvedArguments, args);
    assert.equal(step.riskLevel, "modify");
  }
});

test("document review includes its complete editable title and body", () => {
  const contract = fallbackReviewContract(
    "report.document.create",
    { title: "Launch brief", body: "Full document content" },
    "Reports",
  );
  const step = plannedApprovalStep(
    { tool: "Reports", riskLevel: "modify" },
    {
      consequential: true,
      operation: "report.document.create",
      arguments: { title: "Launch brief", body: "Full document content" },
    },
    "Reports",
  );

  assert.equal(contract.kind, "document");
  assert.equal(step.preview.docTitle, "Launch brief");
  assert.equal(step.preview.docBody, "Full document content");
});

test("one combined preview is required only for consequential plans", () => {
  assert.equal(requiresActionPreview([{ riskLevel: "read" }, { riskLevel: "modify" }]), true);
  assert.equal(requiresActionPreview([{ riskLevel: "read" }]), false);
  assert.equal(requiresActionPreview([{ riskLevel: "modify" }], true), false);
});

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

test("unresolved workflow references can never become an approval preview", () => {
  const unresolved = {
    title: "Berlin weather",
    phases: [{ items: ["{{steps.weather.summary}}"] }],
  };
  assert.equal(hasUnresolvedWorkflowReference(unresolved), true);

  const step = resolvedApprovalStep(
    { tool: "Canva", title: "Create the report", riskLevel: "modify" },
    {
      consequential: true,
      operation: "canva.presentation.create",
      approval_status: "pending",
      approval_preview: { status: "ready", arguments: unresolved },
    },
    "Canva",
  );

  assert.equal(step.approvalPending, true);
  assert.equal(step.preview, undefined);
  assert.equal(step.riskLevel, "read");
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

test("the connected Gmail account alias is accepted by the review contract", () => {
  const contract = {
    fields: [{
      key: "to",
      path: ["to"],
      type: "string",
      required: true,
      pattern: "^(?:me|[^\\s@]+@[^\\s@]+\\.[^\\s@]+)$",
    }],
  };

  assert.deepEqual(validateReviewArguments(contract, { to: "me" }), []);
  assert.deepEqual(validateReviewArguments(contract, { to: "person@example.com" }), []);
  assert.equal(validateReviewArguments(contract, { to: "not an address" }).length, 1);
});

test("derived Canva export stays in preparation instead of becoming another approval", () => {
  const step = resolvedApprovalStep(
    { tool: "Canva", title: "Export presentation", riskLevel: "modify" },
    {
      consequential: false,
      operation: "canva.export.create",
      status: "pending",
    },
    "Canva",
  );

  assert.equal(step.riskLevel, "read");
  assert.equal(step.approvalPending, false);
});
