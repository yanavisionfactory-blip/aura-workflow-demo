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
let temporary, dom, ExecutionView, ToolOutputReview, createRoot, Simulate;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".execution-preview-"));
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    define: { "import.meta.env.VITE_AURA_API_URL": JSON.stringify("https://api.example.invalid") },
    resolve: { alias: [
      { find: "@/api/auraClient", replacement: "\0preview-model" },
      { find: "@/api/base44Client", replacement: "\0no-live-planner" },
      { find: "framer-motion", replacement: "\0instant-motion" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "execution-preview-test", enforce: "pre",
      load(id) {
        if (id === "\0preview-model") return "export const aura = { integrations: { Core: { InvokeLLM: (...args) => globalThis.__resultEditorModel(...args) } } };";
        if (id === "\0no-live-planner") return "export const base44 = {};";
        if (id === "\0instant-motion") return `import React from "react";
          export const AnimatePresence = ({children}) => children;
          const plain = (tag) => ({initial, animate, exit, transition, whileHover, whileTap, ...props}) => React.createElement(tag, props);
          export const motion = { div: plain("div"), button: plain("button") };`;
      },
    }],
    build: { ssr: path.join(repo, "tests/fixtures/executionPreview.jsx"), outDir: temporary,
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
  for (const key of ["Node", "NodeFilter", "HTMLInputElement", "CustomEvent", "MutationObserver", "getComputedStyle"]) globalThis[key] = dom.window[key];
  ({ createRoot } = await import("react-dom/client"));
  ({ Simulate } = await import("react-dom/test-utils"));
  const fixture = await import(pathToFileURL(path.join(temporary, "wait.mjs")));
  ({ ExecutionView, ToolOutputReview } = fixture);
});
after(async () => {
  await new Promise((resolve) => setTimeout(resolve, 30));
  globalThis.fetch = originalFetch;
  dom?.window.close();
  for (const key of ["window", "document", "localStorage", "Element", "HTMLElement", "SVGElement", "requestAnimationFrame", "cancelAnimationFrame", "IS_REACT_ACT_ENVIRONMENT", "Node", "NodeFilter", "HTMLInputElement", "CustomEvent", "MutationObserver", "getComputedStyle", "__resultEditorModel"]) delete globalThis[key];
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else delete globalThis.navigator;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});

const draft = { id: "draft", key: "draft", tool: "anthropic", status: "completed",
  action: "Prepare KPI layout", output: { operation: "anthropic.chat", critic: { action: "accept" },
    outcome_check: { status: "verified" }, provider_result: {
      ret: { content: [{ type: "text", text: "Original dashboard" }] },
    } } };
const review = { step_id: "draft", step_ids: ["draft"], tool_slug: "anthropic", next_tool_slug: "google-sheets" };

test("content signoff is explicit and unsaved edits do not inherit computed checks or approval", async () => {
  const quality = { status: "passed", body_words: 71, comment_ids: ["C01"], content_sha256: "saved-version" };
  const source = { ...draft, tool: "aura", operation: "report.compose", output: { ...draft.output,
    operation: "report.compose", provider_result: { title: "Email", status: "draft", body: "Reviewed email",
      sources: [], quality_check: quality }, content_signoff: { decision: "approved", approver_subject: "alice",
      approved_at: "2026-11-10T10:00:00Z", sha256: "saved-version" } } };
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const approvals = [];
  const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  try {
    await act(async () => root.render(React.createElement(ToolOutputReview, {
      steps: [source], review: { ...review, tool_slug: "aura", review_kind: "content_signoff", is_final: true },
      onApprove: (edits) => approvals.push(edits),
    })));
    assert.ok(button("Approve this content version"));
    assert.match(container.textContent, /designated supervisor/);
    assert.match(container.textContent, /71 body words/);
    assert.match(container.textContent, /Approval recorded for this exact version by alice/);
    await act(async () => Simulate.click(button("Edit manually")));
    await act(async () => Simulate.change(container.querySelector("textarea"), { target: { value: "A new unsaved version" } }));
    await act(async () => Simulate.click(button("Done editing")));
    assert.match(container.textContent, /A new unsaved version/);
    assert.doesNotMatch(container.textContent, /Computed checks passed|Approval recorded for this exact version/);
    await act(async () => Simulate.click(button("Approve this content version")));
    assert.deepEqual(approvals, [{ draft: "A new unsaved version" }]);
  } finally {
    await act(async () => root.unmount()); container.remove();
  }
});

test("AI edits the current manual draft, returns to preview, supports undo, and waits for approval", async () => {
  const calls = [], approvals = [];
  let resolve;
  globalThis.__resultEditorModel = (request) => {
    calls.push(request); return new Promise((done) => { resolve = done; });
  };
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  try {
    await act(async () => root.render(React.createElement(ToolOutputReview, {
      steps: [draft], review, onApprove: (edits) => approvals.push(edits),
    })));
    assert.ok(button("Edit manually")); assert.ok(button("Edit with AI"));
    await act(async () => Simulate.click(button("Edit manually")));
    await act(async () => Simulate.change(container.querySelector("textarea"), { target: { value: "Manually revised dashboard" } }));
    await act(async () => Simulate.click(button("Done editing")));
    assert.match(container.textContent, /Manually revised dashboard/);
    await act(async () => Simulate.click(button("Edit with AI")));
    assert.equal(button("Apply AI edit").disabled, true);
    await act(async () => Simulate.change(container.querySelector("textarea"), { target: { value: "Add a conversions section" } }));
    await act(async () => { Simulate.submit(container.querySelector("form")); Simulate.submit(container.querySelector("form")); });
    assert.equal(calls.length, 1);
    assert.match(calls[0].prompt, /Manually revised dashboard/);
    assert.match(calls[0].prompt, /Add a conversions section/);
    assert.equal(button("Approve result").disabled, true, "approval waits for the AI response");
    assert.equal(button("Edit manually").disabled, true);
    await act(async () => resolve({ text: "AI revised dashboard with conversions", summary: "Added conversions." }));
    assert.equal(container.querySelector("form"), null);
    assert.equal(container.querySelector("textarea"), null);
    assert.match(container.textContent, /AI revised dashboard with conversions/);
    assert.match(container.textContent, /Unsaved changes/);
    assert.doesNotMatch(container.textContent, /Original dashboard|Manually revised dashboard/);
    assert.deepEqual(approvals, [], "AI suggestions never approve or resume execution");
    await act(async () => Simulate.click(button("Undo AI edit")));
    assert.match(container.textContent, /Manually revised dashboard/);
    await act(async () => Simulate.click(button("Approve result")));
    assert.deepEqual(approvals, [{ draft: "Manually revised dashboard" }]);
  } finally {
    await act(async () => root.unmount()); container.remove();
  }
});

test("AI failure preserves the draft and cancelled or stale responses cannot overwrite a newer edit", async () => {
  const requests = [];
  globalThis.__resultEditorModel = () => new Promise((resolve, reject) => requests.push({ resolve, reject }));
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  const start = async () => {
    await act(async () => Simulate.click(button("Edit with AI")));
    await act(async () => Simulate.change(container.querySelector("textarea"), { target: { value: "Make this shorter" } }));
    await act(async () => Simulate.submit(container.querySelector("form")));
  };
  try {
    await act(async () => root.render(React.createElement(ToolOutputReview, { steps: [draft], review, onApprove: () => {} })));
    await start();
    await act(async () => requests[0].reject(new Error("AI is temporarily unavailable")));
    assert.match(container.querySelector('[role="alert"]').textContent, /temporarily unavailable/);
    assert.match(container.textContent, /Original dashboard/);
    assert.equal(container.querySelector("textarea").value, "Make this shorter");
    assert.equal(button("Approve result").disabled, false);
    await act(async () => Simulate.submit(container.querySelector("form")));
    await act(async () => requests[1].resolve({ text: null, summary: "Invalid" }));
    assert.match(container.querySelector('[role="alert"]').textContent, /incomplete edit/);
    assert.match(container.textContent, /Original dashboard/);
    await act(async () => Simulate.submit(container.querySelector("form")));
    await act(async () => Simulate.click(button("Cancel AI edit")));
    assert.equal(button("Approve result").disabled, false);
    await start();
    await act(async () => requests[2].resolve({ text: "Stale result", summary: "Old request" }));
    assert.doesNotMatch(container.textContent, /Stale result/);
    assert.equal(button("Approve result").disabled, true);
    await act(async () => requests[3].resolve({ text: "Current result", summary: "Shortened" }));
    assert.match(container.textContent, /Current result/);
    assert.equal(button("Approve result").disabled, false);
    await act(async () => Simulate.click(button("Discard edits")));
    assert.match(container.textContent, /Original dashboard/);
    assert.doesNotMatch(container.textContent, /Current result|Unsaved changes/);
    await start();
    await act(async () => root.render(React.createElement(ToolOutputReview, { steps: [{ ...draft, id: "next" }],
      review: { ...review, step_id: "next", step_ids: ["next"] }, onApprove: () => {} })));
    await act(async () => requests[4].resolve({ text: "Previous checkpoint result", summary: "Late" }));
    assert.doesNotMatch(container.textContent, /Previous checkpoint result/);
    assert.match(container.textContent, /Original dashboard/);
  } finally {
    await act(async () => root.unmount()); container.remove();
  }
});

test("result preview is a separate page; edits persist on failure and approval is the only handoff", async () => {
  const calls = [];
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  globalThis.fetch = async () => { throw new Error("Review must not dispatch a provider action"); };
  const render = (props = {}) => React.createElement(ToolOutputReview, {
    steps: [draft], review, onApprove: (edits) => calls.push(edits), ...props,
  });
  const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  try {
    await act(async () => root.render(React.createElement(ExecutionView, {
      steps: [{ ...draft, status: "running" }], currentStepIndex: 0, isReal: true,
    })));
    assert.match(container.textContent, /Running your workflow/);
    assert.equal(container.querySelector('[aria-label="Tool result review"]'), null);
    await act(async () => root.render(render()));
    assert.match(container.textContent, /Review Claude result/);
    assert.match(container.textContent, /Original dashboard/);
    assert.equal(document.activeElement, container.querySelector("h2"));
    assert.equal(container.querySelector('[aria-label="Execution steps"]'), null);
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.doesNotMatch(container.textContent, /Preview Claude|Continue to|Open tool view|Open action preview/);
    assert.equal(container.querySelector("textarea"), null);
    assert.deepEqual(calls, [], "opening the result does not approve anything");

    await act(async () => Simulate.click(button("Edit manually")));
    const editor = container.querySelector("textarea");
    assert.equal(editor.value, "Original dashboard");
    await act(async () => Simulate.change(editor, { target: { value: "" } }));
    assert.equal(button("Approve result").disabled, true);
    await act(async () => Simulate.change(editor, { target: { value: "Revised dashboard" } }));
    await act(async () => Simulate.click(button("Approve result")));
    assert.deepEqual(calls, [{ draft: "Revised dashboard" }]);
    await act(async () => root.render(render({ busy: true })));
    assert.equal(button("Approving…").disabled, true);
    assert.equal(editor.disabled, true);
    await act(async () => root.render(render({ error: "Could not save. Please retry." })));
    assert.match(container.querySelector('[role="alert"]').textContent, /Could not save/);
    assert.equal(editor.value, "Revised dashboard", "failed approvals retain unsaved edits");
    await act(async () => Simulate.click(button("Discard edits")));
    assert.equal(container.querySelector("textarea"), null);
    assert.match(container.textContent, /Original dashboard/);
    await act(async () => Simulate.click(button("Approve result")));
    assert.deepEqual(calls, [{ draft: "Revised dashboard" }, null]);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test("review cannot approve missing output; a new checkpoint starts with its own result", async () => {
  const calls = [];
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const render = (steps, checkpoint = review) => React.createElement(ToolOutputReview, {
    steps, review: checkpoint, onApprove: (edits) => calls.push(edits),
  });
  const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  try {
    await act(async () => root.render(render([{ ...draft, status: "pending", output: null }])));
    assert.equal(button("Approve result").disabled, true);
    assert.doesNotMatch(container.textContent, /Original dashboard/);
    await act(async () => root.render(render([draft])));
    await act(async () => Simulate.click(button("Edit manually")));
    await act(async () => Simulate.change(container.querySelector("textarea"), { target: { value: "Unsaved first result" } }));
    const final = { ...draft, id: "last", key: "last" };
    await act(async () => root.render(render([final], { ...review, step_id: "last", step_ids: ["last"], is_final: true })));
    assert.equal(container.querySelector("textarea"), null);
    assert.doesNotMatch(container.textContent, /Unsaved first result/);
    assert.match(container.textContent, /Original dashboard/);
    await act(async () => Simulate.click(button("Approve and finish")));
    assert.deepEqual(calls, [null]);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
