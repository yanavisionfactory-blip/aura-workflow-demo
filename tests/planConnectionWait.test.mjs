import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";
import { JSDOM } from "jsdom";
import React, { act } from "react";

const repo = fileURLToPath(new URL("../", import.meta.url));
const originalFetch = globalThis.fetch;
const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
let temporary, dom, PlanView, createRoot, Simulate;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".connection-wait-"));
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    define: { "import.meta.env.VITE_AURA_API_URL": JSON.stringify("https://api.example.invalid") },
    resolve: { alias: [
      { find: "@/api/base44Client", replacement: "\0no-live-planner" },
      { find: "framer-motion", replacement: "\0instant-motion" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "connection-wait-test", enforce: "pre",
      load(id) {
        if (id === "\0no-live-planner") return "export const base44 = {};";
        if (id === "\0instant-motion") return `import React from "react";
          export const AnimatePresence = ({children}) => children;
          const plain = (tag) => ({initial, animate, exit, transition, whileHover, whileTap, ...props}) => React.createElement(tag, props);
          export const motion = { div: plain("div"), button: plain("button") };`;
      },
    }],
    build: { ssr: path.join(repo, "tests/fixtures/planConnectionWait.jsx"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "wait.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  process.env.NODE_ENV = "test";
  dom = new JSDOM("<!doctype html><body></body>", { pretendToBeVisual: true, url: "https://aura.example.invalid" });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document,
    localStorage: dom.window.localStorage, Element: dom.window.Element, HTMLElement: dom.window.HTMLElement, SVGElement: dom.window.SVGElement,
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window), IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  ({ createRoot } = await import("react-dom/client"));
  ({ Simulate } = await import("react-dom/test-utils"));
  const fixture = await import(pathToFileURL(path.join(temporary, "wait.mjs")));
  PlanView = fixture.PlanView;
  fixture.setAuraTokenProvider(async () => "test-token");
});
after(async () => {
  await new Promise((resolve) => setTimeout(resolve, 30));
  globalThis.fetch = originalFetch;
  dom?.window.close();
  for (const key of ["window", "document", "localStorage", "Element", "HTMLElement", "SVGElement", "requestAnimationFrame", "cancelAnimationFrame", "IS_REACT_ACT_ENVIRONMENT"]) delete globalThis[key];
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else delete globalThis.navigator;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});

test("the checklist cancels preparation, retries with a focusable sign-in window, and preserves the plan", async () => {
  localStorage.setItem("aura_python_workspace_id", "test-workspace");
  localStorage.setItem("aura_active_python_run_id", "saved-run");
  const popups = [], signals = [], recovered = [], skipped = [];
  window.open = () => {
    const popup = { closed: false, location: {}, focusCount: 0,
      close() { this.closed = true; }, focus() { this.focusCount += 1; } };
    popups.push(popup);
    return popup;
  };
  let finishFirstSession, sessions = 0;
  const session = { backend: "nango", provider: "google", tool_connection_id: "google-account",
    connect_link: "https://connect.example.invalid/google" };
  globalThis.fetch = async (url, options) => {
    const { pathname } = new URL(url);
    if (pathname === "/v1/managed-connectors/status") return Response.json({
      catalog: [{ display_name: "Google Workspace", provider: "google", connection_backend: "nango", connection_strategy: "oauth" }],
    });
    if (pathname === "/v1/tools") return Response.json([{ id: "google-account", slug: "google",
      display_name: "Google Workspace", connection_backend: "nango", kind: "oauth", enabled: false }]);
    if (pathname === "/v1/connector-broker/google/session") {
      signals.push(options.signal);
      if (++sessions === 1) return new Promise((resolve) => { finishFirstSession = resolve; });
      return Response.json(session);
    }
    throw new Error(`Unexpected request: ${pathname}`);
  };
  const plan = { workflowName: "KPI workbook", steps: [{ title: "Create workbook", tool: "Google Sheets",
    toolSlug: "google", operation: "sheets.kpi.create", action: "Create the required KPI workbook" }],
    connectionChecklist: [{ provider_hint: "google", canonical_provider: "google", status: "required",
      reason: "Authorize exact operations for google",
      required_permissions: ["sheets.kpi.create"] }] };
  const originalPlan = JSON.stringify(plan);
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const button = (text) => [...container.querySelectorAll("button")].find((item) => item.textContent.includes(text));
  try {
    await act(async () => root.render(React.createElement(PlanView, {
      plan, onConnectionRecovered: (value) => recovered.push(value), onSkipTool: (value) => skipped.push(value),
    })));
    assert.equal(button("Update Google Sheets access").disabled, false);
    await act(async () => Simulate.click(button("Update Google Sheets access")));
    assert.match(container.textContent, /Preparing Google Sheets sign-in/);
    assert.equal(button("Run without Google Sheets").disabled, true);
    assert.equal(button("Cancel connection").disabled, false);
    await act(async () => Simulate.click(button("Cancel connection")));
    assert.equal(signals[0].aborted, true);
    assert.equal(popups[0].closed, true);
    assert.match(container.textContent, /Connection cancelled\. Your plan is unchanged/);
    assert.equal(button("Update Google Sheets access").disabled, false);
    assert.equal(button("Run without Google Sheets").disabled, false);

    await act(async () => finishFirstSession(Response.json(session)));
    assert.equal(popups.length, 1, "late session cannot reopen a cancelled window");
    assert.equal(popups[0].location.href, undefined);
    await act(async () => Simulate.click(button("Update Google Sheets access")));
    assert.match(container.textContent, /Waiting for Google Sheets sign-in/);
    assert.match(container.textContent, /Finish signing in and approving access in the window/);
    assert.equal(popups[1].location.href, session.connect_link);
    await act(async () => Simulate.click(button("Open sign-in window")));
    assert.equal(popups[1].focusCount, 1);
    await act(async () => Simulate.click(button("Cancel connection")));
    assert.equal(popups[1].closed, true);
    await act(async () => Simulate.click(button("Run without Google Sheets")));
    assert.deepEqual(skipped, ["Google Sheets"]);
    assert.deepEqual(recovered, [], "cancellation never resumes the workflow");
    assert.equal(JSON.stringify(plan), originalPlan);
    assert.equal(localStorage.getItem("aura_active_python_run_id"), "saved-run");
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test("switching a blocked Sheets plan recompiles for review without opening consent or executing", async () => {
  let popups = 0, finishRevision;
  const revisions = [], approvals = [];
  window.open = () => { popups += 1; throw new Error("The switch must not open OAuth"); };
  globalThis.fetch = async (url) => {
    const { pathname } = new URL(url);
    if (pathname === "/v1/managed-connectors/status") return Response.json({ marketplace: [
      { display_name: "Google Workspace", provider: "google", connection_backend: "nango", connectable: true },
      { display_name: "Google Sheets", provider: "google-sheets", connection_backend: "pipedream",
        connectable: true },
    ] });
    if (pathname === "/v1/tools") return Response.json([{ id: "google-account", slug: "google",
      display_name: "Google Workspace", connection_backend: "nango", kind: "oauth", enabled: false }]);
    throw new Error(`Unexpected request: ${pathname}`);
  };
  const plan = { workflowName: "KPI workbook", connectionRoutes: { docs: "google-docs" },
    steps: [{ title: "Create workbook", tool: "Google Sheets", toolSlug: "google",
      operation: "sheets.kpi.create", action: "Create the required KPI workbook" }],
    connectionChecklist: [{ provider_hint: "google", canonical_provider: "google", status: "required",
      required_permissions: ["sheets.kpi.create", "sheets.workbook.get"] }] };
  const original = JSON.stringify(plan);
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const button = (text) => [...container.querySelectorAll("button")].find((item) => item.textContent.includes(text));
  try {
    await act(async () => root.render(React.createElement(PlanView, {
      plan, onApprove: (...args) => approvals.push(args),
      onRevisePlan: (...args) => { revisions.push(args); return new Promise((resolve) => { finishRevision = resolve; }); },
    })));
    assert.equal(button("Use dedicated Google Sheets connection").disabled, false);
    await act(async () => Simulate.click(button("Use dedicated Google Sheets connection")));
    assert.equal(revisions.length, 1);
    assert.deepEqual(revisions[0][1], { connectionRoutes: { docs: "google-docs", sheets: "google-sheets" } });
    assert.match(container.textContent, /Updating your plan/);
    assert.match(container.textContent, /Nothing will run before review/);
    assert.equal(button("Cancel connection"), undefined, "plan rebuilding is not an OAuth attempt");
    assert.equal(button("Use dedicated Google Sheets connection").disabled, true);
    await act(async () => finishRevision({ ok: false, error: "The revised plan needs another review." }));
    assert.match(container.textContent, /The revised plan needs another review/);
    assert.equal(button("Use dedicated Google Sheets connection").disabled, false);
    assert.equal(popups, 0);
    assert.deepEqual(approvals, []);
    assert.equal(JSON.stringify(plan), original);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
