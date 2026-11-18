import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { desktopPairingDialog } from "../src/lib/desktopPairingDialog.js";

async function withDocument(run, { userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", platform = "Win32", userAgentData } = {}) {
  const dom = new JSDOM("<!doctype html><body></body>", { url: "https://aura.example/?private=query#private-fragment" });
  Object.defineProperties(dom.window.navigator, {
    userAgent: { value: userAgent }, platform: { value: platform }, userAgentData: { value: userAgentData },
  });
  const original = globalThis.document;
  globalThis.document = dom.window.document;
  dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  try { await run(dom); } finally { globalThis.document = original; dom.window.close(); }
}

test("PlanSwift Connect requests only PlanSwift access without key fields", () => withDocument(async () => {
  let finish;
  const pending = new Promise((resolve) => { finish = resolve; });
  const result = desktopPairingDialog({
    start: async () => ({ pairing_id: "pair", code: "temporary-authorization-code", provider: "planswift" }),
    status: () => pending,
    cancel: () => assert.fail("Do not cancel a successful grant"),
  }, { provider: "planswift" });
  document.querySelector("[data-start]").click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(document.querySelectorAll("input").length, 0);
  assert.doesNotMatch(document.querySelector("dialog").textContent, /Excel/);
  assert.equal(document.querySelector("h2").textContent, "Connect PlanSwift");
  assert.match(document.querySelector("[data-open]").href, /^aura-estimator:\/\/pair\?code=/);
  assert.equal(document.querySelector("[data-open]").hidden, false);
  finish({ status: "verified", connections: [{ id: "ps", provider: "planswift" }] });
  assert.equal((await result).id, "ps");
  assert.equal(document.querySelector("dialog"), null);
}));

test("Excel Connect has its own name and permissions and never requires PlanSwift", () => withDocument(async (dom) => {
  const result = desktopPairingDialog({
    start: async () => ({ pairing_id: "excel-pair", code: "code", provider: "excel-desktop" }),
    status: async () => ({ status: "waiting" }),
    cancel: async () => {},
  }, { provider: "excel-desktop" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(document.querySelector("h2").textContent, "Connect Microsoft Excel (Desktop)");
  assert.doesNotMatch(document.querySelector("dialog").textContent, /PlanSwift|measurements/);
  assert.match(document.querySelector("dialog").textContent, /only this app/);
  document.querySelector("[data-cancel]").dispatchEvent(new dom.window.Event("click"));
  await assert.rejects(result, /window closed/);
}));

test("a stalled check reaches a visible deadline and can be cancelled", () => withDocument(async (dom) => {
  const cancelled = [];
  let requestSignal;
  const result = desktopPairingDialog({
    start: async () => ({ pairing_id: "pair", code: "code", provider: "excel-desktop" }),
    status: (_id, signal) => { requestSignal = signal; return new Promise(() => {}); },
    cancel: async (id) => cancelled.push(id),
  }, { provider: "excel-desktop" }, undefined, { waitMs: 20, pollMs: 1 });
  document.querySelector("[data-start]").click();
  await new Promise((resolve) => setTimeout(resolve, 35));
  assert.equal(requestSignal.aborted, true);
  assert.equal(document.querySelector("[data-retry]").hidden, false);
  assert.match(document.querySelector("[data-status]").textContent, /approval window expired/);
  assert.equal(document.querySelector("[data-error]").hidden, true);
  assert.equal(document.querySelector("[data-open]").hidden, true);
  assert.equal(document.querySelector("[data-open]").hasAttribute("href"), false);
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
  document.querySelector("[data-start]").click();
  controller.abort();
  await assert.rejects(result, /window closed/);
  created({ pairing_id: "late", code: "code" });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(cancelled, ["late"]);
  assert.equal(document.querySelector("dialog"), null);
}));

test("Windows installation does not start a grant or deadline until the user is ready", () => withDocument(async () => {
  const calls = [];
  const result = desktopPairingDialog({
    start: async () => { calls.push("start"); return { pairing_id: "pair", code: "code", provider: "planswift" }; },
    status: async () => { calls.push("status"); return { status: "verified", connections: [{ id: "ps", provider: "planswift" }] }; },
    cancel: () => assert.fail("No grant should be cancelled"),
  }, { provider: "planswift" }, undefined, { waitMs: 20, pollMs: 1 });
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.deepEqual(calls, []);
  assert.match(document.querySelector("[data-status]").textContent, /Take as long as you need/);
  assert.equal(document.querySelector("[data-retry]").hidden, true);
  assert.equal(document.querySelector("[data-open]").hidden, true);
  document.querySelector("[data-start]").click();
  assert.equal((await result).id, "ps");
  assert.deepEqual(calls, ["start", "status"]);
}));

for (const [device, browser] of Object.entries({
  iPhone: { userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148", platform: "iPhone" },
  Android: { userAgent: "Mozilla/5.0 (Linux; Android 15) Chrome/131.0 Mobile", platform: "Linux armv8l" },
  iPad: { userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605.1", platform: "MacIntel" },
  Mac: { userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)", platform: "MacIntel" },
  Linux: { userAgent: "Mozilla/5.0 (X11; Linux x86_64)", platform: "Linux x86_64" },
  unknown: { userAgent: "", platform: "" },
  mobileClientHints: { userAgent: "", platform: "Win32", userAgentData: { platform: "Windows", mobile: true } },
})) {
  for (const provider of ["planswift", "excel-desktop"]) {
    test(`${device} ${provider} setup offers a public link without starting Windows authorization`, () => withDocument(async (dom) => {
      let copied;
      Object.defineProperty(dom.window.navigator, "clipboard", { value: { writeText: async (value) => { copied = value; } } });
      const result = desktopPairingDialog({
        start: () => assert.fail("Do not create a grant on this device"),
        status: () => assert.fail("Do not poll on this device"),
        cancel: () => assert.fail("No grant exists to cancel"),
      }, { provider }, undefined, { waitMs: 5, pollMs: 1 });
      await new Promise((resolve) => setTimeout(resolve, 15));
      assert.match(document.querySelector("dialog").textContent, /Continue on your Windows computer/);
      for (const selector of ["a[download]", "[data-open]", "[data-copy]", "[data-start]", "[data-retry]", "[data-error]"]) {
        assert.equal(document.querySelector(selector), null);
      }
      assert.doesNotMatch(document.querySelector("dialog").textContent, /expired|remaining|Try again|helper|API key/);
      document.querySelector("[data-copy-link]").click();
      await new Promise((resolve) => setImmediate(resolve));
      assert.equal(copied, "https://aura.example/");
      assert.match(document.querySelector("[data-status]").textContent, /Link copied/);
      document.querySelector("[data-cancel]").click();
      await assert.rejects(result, /window closed/);
    }, browser));
  }
}

test("a device without clipboard access still has a visible link to continue on Windows", () => withDocument(async () => {
  const result = desktopPairingDialog({}, { provider: "planswift" });
  document.querySelector("[data-copy-link]").click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(document.querySelector("[data-workspace-link]").href, "https://aura.example/");
  assert.match(document.querySelector("[data-status]").textContent, /Copy the link above/);
  document.querySelector("[data-cancel]").click();
  await assert.rejects(result, /window closed/);
}, { userAgent: "iPhone", platform: "iPhone" }));
