import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";
import { JSDOM } from "jsdom";
import React, { act } from "react";

const repo = fileURLToPath(new URL("../", import.meta.url));
const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
let temporary, dom, PlanStep, createRoot, Simulate;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".plan-editor-"));
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: { alias: [
      { find: "@/api/base44Client", replacement: "\0no-live-planner" },
      { find: "framer-motion", replacement: "\0instant-motion" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "no-live-planner", enforce: "pre",
      resolveId(source) { if (source === "@/api/base44Client") return "\0no-live-planner"; },
      load(id) {
        if (id === "\0no-live-planner") return "export const base44 = {};";
        if (id === "\0instant-motion") return `import React from "react";
          export const AnimatePresence = ({children}) => children;
          export const motion = { div: ({initial, animate, exit, transition, ...props}) => React.createElement("div", props) };`;
      },
    }],
    build: { ssr: path.join(repo, "tests/fixtures/planStepEditor.jsx"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "editor.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  process.env.NODE_ENV = "test";
  dom = new JSDOM("<!doctype html><body></body>", { pretendToBeVisual: true, url: "https://aura.example.invalid" });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document,
    HTMLElement: dom.window.HTMLElement, SVGElement: dom.window.SVGElement,
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window), IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  ({ createRoot } = await import("react-dom/client"));
  ({ Simulate } = await import("react-dom/test-utils"));
  ({ PlanStep } = await import(pathToFileURL(path.join(temporary, "editor.mjs"))));
});
after(() => {
  dom?.window.close();
  for (const key of ["window", "document", "HTMLElement", "SVGElement", "requestAnimationFrame", "cancelAnimationFrame", "IS_REACT_ACT_ENVIRONMENT"]) delete globalThis[key];
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else delete globalThis.navigator;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});

test("Update step waits for the revised plan, preserves a failed edit, and closes only on success", async () => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  let resolveRevision, calls = [];
  const change = "Add a Leads tab";
  try {
    await act(async () => root.render(React.createElement(PlanStep, {
      step: { title: "Create workbook", action: "Create a KPI workbook", tool: "Google Sheets" },
      index: 0, isLast: true, provided: { innerRef: () => {}, draggableProps: {}, dragHandleProps: {} },
      forceEdit: true, onEditConsumed: () => {},
      onRequestChange: (text) => { calls.push(text); return new Promise((resolve) => { resolveRevision = resolve; }); },
    })));
    await act(async () => Simulate.change(container.querySelector("textarea"), { target: { value: change } }));
    const update = () => [...container.querySelectorAll("button")].find((button) => /Update step/.test(button.textContent));
    await act(async () => Simulate.click(update()));
    assert.deepEqual(calls, [change]);
    assert.equal(container.querySelector("textarea").value, change);
    assert.match(container.textContent, /Updating/);
    await act(async () => resolveRevision({ ok: false, error: "Planning is temporarily unavailable" }));
    assert.equal(container.querySelector("textarea").value, change);
    assert.match(container.textContent, /Planning is temporarily unavailable/);
    assert.equal(update().disabled, false);
    await act(async () => Simulate.click(update()));
    await act(async () => resolveRevision({ ok: true }));
    assert.deepEqual(calls, [change, change]);
    assert.equal(container.querySelector("textarea"), null);
    assert.doesNotMatch(container.textContent, /Planning is temporarily unavailable/);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
