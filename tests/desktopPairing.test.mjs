import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { desktopPairingDialog } from "../src/lib/desktopPairingDialog.js";

async function withDocument(run) {
  const dom = new JSDOM("<!doctype html><body></body>");
  const original = globalThis.document;
  globalThis.document = dom.window.document;
  dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  try { await run(dom); } finally { globalThis.document = original; dom.window.close(); }
}

test("normal Connect authorizes both apps with no secret or endpoint fields", () => withDocument(async () => {
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const result = desktopPairingDialog({
    start: async () => ({ pairing_id: "pair", code: "temporary-authorization-code" }),
    status: () => pending,
    cancel: () => assert.fail("Do not cancel a successful grant"),
  }, { provider: "planswift" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(document.querySelectorAll("input").length, 0);
  assert.equal(document.querySelector("h2").textContent, "Connect your computer");
  assert.match(document.querySelector("[data-open]").href, /^aura-estimator:\/\/pair\?code=/);
  assert.equal(document.querySelector("[data-open]").hidden, false);
  finish({ status: "verified", connections: [{ id: "ps", provider: "planswift" }, { id: "xl", provider: "excel-desktop" }] });
  assert.equal((await result).id, "ps");
  assert.equal(document.querySelector("dialog"), null);
}));

test("a stalled check reaches a visible deadline and can be cancelled", () => withDocument(async (dom) => {
  const cancelled = [];
  let requestSignal;
  const result = desktopPairingDialog({
    start: async () => ({ pairing_id: "pair", code: "code" }),
    status: (_id, signal) => { requestSignal = signal; return new Promise(() => {}); },
    cancel: async (id) => cancelled.push(id),
  }, { provider: "excel-desktop" }, undefined, { waitMs: 20, pollMs: 1 });
  await new Promise((resolve) => setTimeout(resolve, 35));
  assert.equal(requestSignal.aborted, true);
  assert.equal(document.querySelector("[data-retry]").hidden, false);
  assert.match(document.querySelector("[data-error]").textContent, /No response/);
  assert.deepEqual(cancelled, ["pair"]);
  document.querySelector("[data-cancel]").dispatchEvent(new dom.window.Event("click"));
  await assert.rejects(result, /window closed/);
}));

test("late session creation after cancel cannot leave an active pairing grant", () => withDocument(async () => {
  let created;
  const cancelled = [];
  const controller = new AbortController();
  const result = desktopPairingDialog({
    start: () => new Promise((resolve) => { created = resolve; }),
    status: () => assert.fail("Never poll after cancellation"),
    cancel: async (id) => cancelled.push(id),
  }, { provider: "planswift" }, controller.signal);
  controller.abort();
  await assert.rejects(result, /window closed/);
  created({ pairing_id: "late", code: "code" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(cancelled, ["late"]);
  assert.equal(document.querySelector("dialog"), null);
}));
