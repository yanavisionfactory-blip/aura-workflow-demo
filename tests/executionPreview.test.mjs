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
let temporary, dom, ExecutionView, ExecutionToolOutputs, createRoot, Simulate;
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
  ({ ExecutionView, ExecutionToolOutputs } = fixture);
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

test("execution leads; saved output opens only on request and never continues or approves the run", async () => {
  const steps = [{ id: "draft", key: "draft", tool: "anthropic", status: "completed",
    action: "Prepare KPI layout", output: { operation: "anthropic.generate", provider_result: {
      text: "Plantea September 2026 KPI layout: revenue, sales and conversions.",
    } } }, { id: "sheet", key: "sheet", tool: "google-sheets", status: "pending", action: "Create workbook" }];
  const review = { step_id: "draft", step_ids: ["draft"], tool_slug: "anthropic", next_tool_slug: "google-sheets" };
  let continued = 0, previewRequested = 0;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  globalThis.fetch = async () => { throw new Error("Viewing outputs must not dispatch an action"); };
  const render = (approvalPending = false) => React.createElement(ExecutionView, {
    steps, currentStepIndex: 1, isReal: true, review: approvalPending ? null : review, approvalPending,
    onOpenPreview: () => { previewRequested += 1; },
  }, React.createElement(ExecutionToolOutputs, {
    steps, review: approvalPending ? null : review, onContinue: () => { continued += 1; },
  }));
  try {
    await act(async () => root.render(render()));
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.doesNotMatch(container.textContent, /Plantea September 2026 KPI layout/);
    const timeline = container.querySelector('[aria-label="Execution steps"]');
    const checkpoint = container.querySelector('[aria-label="Tool output checkpoint"]');
    assert.ok(timeline.compareDocumentPosition(checkpoint) & window.Node.DOCUMENT_POSITION_FOLLOWING);
    const preview = [...container.querySelectorAll("button")].find((button) => button.textContent.startsWith("Preview Claude"));
    assert.ok(preview);
    await act(async () => Simulate.click(preview));
    assert.match(document.querySelector('[role="dialog"]').textContent, /Plantea September 2026 KPI layout/);
    assert.equal(continued, 0);
    assert.equal(previewRequested, 0);
    const close = [...document.querySelector('[role="dialog"]').querySelectorAll("button")].find((button) => button.textContent === "Close");
    await act(async () => Simulate.click(close));
    assert.equal(document.querySelector('[role="dialog"]'), null);

    await act(async () => root.render(render(true)));
    assert.match(container.textContent, /Execution paused for approval/);
    assert.doesNotMatch(container.textContent, /Plantea September 2026 KPI layout/);
    assert.equal(previewRequested, 0, "arriving at approval does not open preview automatically");
    const open = [...container.querySelectorAll("button")].find((button) => button.textContent === "Open action preview");
    await act(async () => Simulate.click(open));
    assert.equal(previewRequested, 1);
    assert.equal(continued, 0, "opening preview never approves the write");
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

