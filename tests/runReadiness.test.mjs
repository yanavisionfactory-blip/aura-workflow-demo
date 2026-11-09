import test, { before, after, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";
import { JSDOM } from "jsdom";
import React, { act, useState } from "react";

const repo = fileURLToPath(new URL("../", import.meta.url));
const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
let temporary, dom, RunReadiness, createRoot, root, container;
let calls, requests, starts;
const backendPlan = { steps: [{ key: "read", tool_slug: "google", operation: "sheets.read",
  arguments: { spreadsheet_id: "approved-sheet", range: "A1:B5" } }] };
const initialPlan = { workflowName: "Review sheet" };
const initialSteps = [{ arguments: backendPlan.steps[0].arguments }];

function Review({ runId = "run", plan = initialPlan, steps = initialSteps }) {
  const [ready, setReady] = useState(false);
  return React.createElement(React.Fragment, null,
    React.createElement(RunReadiness, { runId, plan, backendPlan, steps, onReady: setReady }),
    React.createElement("button", { disabled: !ready, onClick: () => { starts += 1; } }, "Start"));
}

function report(overrides = {}) {
  return { passed: true, checked_at: new Date(Date.now()).toISOString(),
    expires_at: new Date(Date.now() + 60000).toISOString(),
    checks: [{ status: "passed", message: "Google: account and required capabilities verified." }],
    ...overrides };
}

const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent === label);
const render = (props = {}) => act(async () => root.render(React.createElement(Review, props)));
const resolve = (index, data = report()) => act(async () => requests[index].resolve(data));

function browserClock(t) {
  let now = Date.now(), sequence = 0;
  const timers = new Map();
  t.mock.method(Date, "now", () => now);
  t.mock.method(window, "setTimeout", (callback, delay) => {
    const id = ++sequence;
    timers.set(id, { callback, at: now + delay });
    return id;
  });
  t.mock.method(window, "clearTimeout", (id) => timers.delete(id));
  return async (milliseconds) => act(async () => {
    now += milliseconds;
    for (const [id, timer] of timers) {
      if (timer.at <= now) { timers.delete(id); timer.callback(); }
    }
  });
}

before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".readiness-test-"));
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: { alias: [
      { find: "@/lib/auraApi", replacement: "\0readiness-api" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "readiness-api", load(id) {
      if (id === "\0readiness-api") return "export const auraRequest = (...args) => globalThis.__readinessRequest(...args);";
    } }],
    build: { ssr: path.join(repo, "src/components/aura/RunReadiness.jsx"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "readiness.mjs" } } },
  });
  process.env.NODE_ENV = "test";
  dom = new JSDOM("<!doctype html><body></body>", { url: "https://aura.example.invalid" });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document,
    HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  ({ createRoot } = await import("react-dom/client"));
  ({ default: RunReadiness } = await import(pathToFileURL(path.join(temporary, "readiness.mjs"))));
});

beforeEach(() => {
  calls = []; requests = []; starts = 0;
  globalThis.__readinessRequest = (...args) => {
    calls.push(args);
    return new Promise((resolve, reject) => requests.push({ resolve, reject }));
  };
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  delete globalThis.__readinessRequest;
});

after(() => {
  dom?.window.close();
  for (const key of ["window", "document", "HTMLElement", "IS_REACT_ACT_ENVIRONMENT"]) delete globalThis[key];
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else delete globalThis.navigator;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});

test("a passed review keeps Start usable after one minute without background probes", async (t) => {
  const advance = browserClock(t);
  await render();
  assert.equal(button("Start").disabled, true);
  await resolve(0);
  assert.equal(button("Start").disabled, false);
  await advance(61000);
  assert.equal(button("Start").disabled, false);
  assert.equal(calls.length, 1);
  assert.match(container.textContent, /Start checks access again before running anything/);
  assert.doesNotMatch(container.textContent, /check again if Start becomes unavailable/);
  await act(async () => button("Start").click());
  assert.equal(starts, 1);
});

test("a slow check whose snapshot is already expired can still reach the server's Start gate", async (t) => {
  const advance = browserClock(t);
  await render();
  await resolve(0, report({ expires_at: new Date(Date.now() - 1).toISOString() }));
  await advance(1);
  assert.equal(button("Start").disabled, false);
});

test("failed checks keep Start disabled and an explicit successful recheck restores it", async () => {
  await render();
  await resolve(0, report({ passed: false, checks: [{ status: "blocked", message: "Reconnect Google" }] }));
  assert.equal(button("Start").disabled, true);
  assert.match(container.textContent, /Reconnect Google/);
  await act(async () => button("Check again").click());
  assert.equal(button("Start").disabled, true);
  assert.equal(button("Check again").disabled, true);
  await resolve(1);
  assert.equal(button("Start").disabled, false);
});

test("manual rechecks revoke previous readiness while pending and after request failures", async () => {
  await render();
  await resolve(0);
  await act(async () => button("Check again").click());
  assert.equal(button("Start").disabled, true);
  await act(async () => requests[1].reject(new Error("Could not verify access")));
  assert.equal(button("Start").disabled, true);
  assert.match(container.querySelector('[role="alert"]').textContent, /Could not verify access/);
  assert.equal(button("Check again").disabled, false);
});

test("edited arguments must pass a new check before Start", async () => {
  await render();
  await resolve(0);
  const steps = [{ arguments: { spreadsheet_id: "another-sheet", range: "A1:B5" } }];
  await render({ steps });
  assert.equal(button("Start").disabled, true);
  assert.equal(JSON.parse(calls[1][1].body).edited_steps[0].arguments.spreadsheet_id, "another-sheet");
  await resolve(1);
  assert.equal(button("Start").disabled, false);
});

test("a response for the previous run cannot unlock a new run", async () => {
  await render();
  await render({ runId: "new/run" });
  assert.equal(calls[1][0], "/v1/runs/new%2Frun/preflight");
  await resolve(0);
  assert.equal(button("Start").disabled, true);
  await resolve(1, report({ passed: false }));
  assert.equal(button("Start").disabled, true);
});
