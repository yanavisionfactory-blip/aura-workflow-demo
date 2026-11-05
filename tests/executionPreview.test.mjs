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
      { find: "@/api/base44Client", replacement: "\0no-live-planner" },
      { find: "framer-motion", replacement: "\0instant-motion" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "execution-preview-test", enforce: "pre",
      load(id) {
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
  for (const key of ["window", "document", "localStorage", "Element", "HTMLElement", "SVGElement", "requestAnimationFrame", "cancelAnimationFrame", "IS_REACT_ACT_ENVIRONMENT", "Node", "NodeFilter", "HTMLInputElement", "CustomEvent", "MutationObserver", "getComputedStyle"]) delete globalThis[key];
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

    await act(async () => Simulate.click(button("Edit Claude result")));
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
    await act(async () => Simulate.click(button("Edit Claude result")));
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
