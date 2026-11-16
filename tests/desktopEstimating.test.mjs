import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { desktopEstimatingDialog } from "../src/lib/desktopEstimatingDialog.js";
import { primaryResultFromOutputs } from "../src/lib/resultPresentation.mjs";

test("only verified, accepted Excel creation or readback offers a report download", () => {
  for (const operation of ["excel.estimate.create", "excel.estimate.get"]) {
    const output = { operation, step_key: "estimate", critic: { action: "accept" },
      outcome_check: { status: "verified" }, provider_result: {
        report_id: "a".repeat(64), status: "draft", total: 88.55, currency: "USD", row_count: 2,
        formula_errors: 0, recalculated_with: "Microsoft Excel",
      } };
    const result = primaryResultFromOutputs([output], {}, { primary_step_key: "estimate" });
    assert.equal(result.kind, "desktop_estimate");
    assert.equal(result.receipt.total, 88.55);
    assert.equal(result.link, null);
    for (const mutate of [
      (item) => { item.outcome_check.status = "unverified"; },
      (item) => { item.critic.action = "escalate"; },
      (item) => { item.provider_result.formula_errors = 1; },
      (item) => { item.provider_result.recalculated_with = "simulator"; },
      (item) => { item.provider_result.report_id = "../../another-report"; },
      (item) => { item.provider_result.total = Infinity; },
    ]) {
      const invalid = structuredClone(output); mutate(invalid);
      assert.notEqual(primaryResultFromOutputs([invalid]).kind, "desktop_estimate");
    }
  }
});

test("desktop connect form clears its key and submits only the selected application", async () => {
  const dom = new JSDOM("<!doctype html><body></body>");
  const original = { document: globalThis.document, FormData: globalThis.FormData };
  globalThis.document = dom.window.document;
  globalThis.FormData = dom.window.FormData;
  dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  try {
    let submitted;
    const connected = desktopEstimatingDialog(async (payload) => {
      submitted = payload;
      assert.equal(document.querySelector('input[type="password"]').value, "");
      return { id: "verified-connection" };
    }, { provider: "planswift" });
    const form = document.querySelector("form");
    form.elements.endpoint.value = "https://workstation.example.com";
    form.elements.connection_key.value = "test-connection-key-01234567890123456789";
    form.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
    assert.deepEqual(await connected, { id: "verified-connection" });
    assert.equal(submitted.provider, "planswift");
    assert.equal(submitted.endpoint, "https://workstation.example.com");
    assert.equal(submitted.connection_id, null);
    assert.equal(document.querySelector("dialog"), null);
    const controller = new AbortController();
    const cancelled = desktopEstimatingDialog(() => assert.fail("Must not submit"), { provider: "excel-desktop" }, controller.signal);
    controller.abort();
    await assert.rejects(cancelled, /cancelled/);
    assert.equal(document.querySelector("dialog"), null);
  } finally {
    globalThis.document = original.document;
    globalThis.FormData = original.FormData;
    dom.window.close();
  }
});
