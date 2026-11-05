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
let temporary, dom, Demo, MemoryRouter, createRoot, Simulate;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".restored-workflow-"));
  const apiExports = [...fs.readFileSync(path.join(repo, "src/lib/auraApi.js"), "utf8")
    .matchAll(/^export (?:async )?(?:function|const) (\w+)/gm)].map((match) => match[1]);
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: { alias: [
      { find: "@/lib/auraApi", replacement: "\0saved-run-api" },
      { find: "@/api/auraClient", replacement: "\0saved-run-history" },
      { find: "@/api/base44Client", replacement: "\0no-live-planner" },
      { find: "@/lib/connectService", replacement: "\0no-connections" },
      { find: "framer-motion", replacement: "\0instant-motion" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "restored-workflow-test", enforce: "pre",
      resolveId(id, importer) {
        if (importer?.endsWith("/src/pages/Demo.jsx") && id.includes("/components/aura/")
            && !/\/(ExecutionView|ExecutionToolOutputs)(\.jsx)?$/.test(id)) {
          return `\0shell:${path.basename(id).replace(/\.jsx$/, "")}`;
        }
      },
      load(id) {
        if (id === "\0saved-run-api") return apiExports.map((name) =>
          `export const ${name} = (...args) => globalThis.__savedRunHarness.api(${JSON.stringify(name)}, args);`).join("\n");
        if (id === "\0saved-run-history") return `export const aura = { entities: {
          WorkflowRun: { filter: async () => [{id: "history", workflow_id: "workflow"}] }
        } };`;
        if (id === "\0no-live-planner") return "export const base44 = {};";
        if (id === "\0no-connections") return "export const connectTool = () => { throw new Error('Unexpected connection'); };";
        if (id === "\0instant-motion") return `import React from "react";
          export const AnimatePresence = ({children}) => children;
          const plain = (tag) => ({initial, animate, exit, transition, whileHover, whileTap, ...props}) => React.createElement(tag, props);
          export const motion = { div: plain("div"), button: plain("button") };`;
        if (id === "\0shell:WorkspaceShell") return `import React from "react";
          export default ({children}) => React.createElement("div", null, children);`;
        if (id === "\0shell:HistoryPanel") return `import React from "react";
          export default ({open, onOpenRun}) => open && React.createElement("button", {
            onClick: () => onOpenRun("saved") }, "Open saved workflow");`;
        if (id.startsWith("\0shell:")) return "export default () => null;";
      },
    }],
    build: { ssr: path.join(repo, "tests/fixtures/restoredWorkflow.jsx"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "restore.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  dom = new JSDOM("<!doctype html><body></body>", { pretendToBeVisual: true, url: "https://aura.example.invalid" });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document,
    localStorage: dom.window.localStorage, Element: dom.window.Element, HTMLElement: dom.window.HTMLElement,
    SVGElement: dom.window.SVGElement, requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
    cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window), IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  for (const key of ["Node", "NodeFilter", "HTMLInputElement", "CustomEvent", "MutationObserver", "getComputedStyle"]) globalThis[key] = dom.window[key];
  ({ createRoot } = await import("react-dom/client"));
  ({ Simulate } = await import("react-dom/test-utils"));
  ({ Demo, MemoryRouter } = await import(pathToFileURL(path.join(temporary, "restore.mjs"))));
});
after(() => {
  dom?.window.close();
  for (const key of ["window", "document", "localStorage", "Element", "HTMLElement", "SVGElement", "requestAnimationFrame", "cancelAnimationFrame", "IS_REACT_ACT_ENVIRONMENT", "Node", "NodeFilter", "HTMLInputElement", "CustomEvent", "MutationObserver", "getComputedStyle", "__savedRunHarness"]) delete globalThis[key];
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else delete globalThis.navigator;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});

const waitUntil = async (predicate) => {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (predicate()) return;
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  }
  assert.ok(predicate(), "workflow did not reach the expected visible state");
};

for (const entry of ["refresh", "history"]) test(`${entry} resumes the saved 0/3 run and first offers review after tool completion`, async () => {
  const calls = [];
  const steps = [
    { key: "draft", tool_slug: "anthropic", operation: "anthropic.chat", consequential: true },
    { key: "sheet", tool_slug: "google-sheets", operation: "sheets.create", consequential: true },
    { key: "rows", tool_slug: "google-sheets", operation: "sheets.append", consequential: true },
  ].map((step, position) => ({ ...step, id: step.key, position, arguments: {},
    status: "awaiting_approval", approval_status: "pending", approval_id: `approval-${position}`,
    approval_preview: { status: "ready", arguments: {} } }));
  let run = { id: "saved", plan_approved: true, status: "awaiting_approval",
    prompt: "Create a KPI dashboard", plan: { name: "Dashboard", steps }, steps };
  globalThis.__savedRunHarness = { api(name, args) {
    calls.push({ name, args });
    if (name === "rememberedActivePythonRun") return entry === "refresh" ? "saved" : null;
    if (["rememberActivePythonRun", "forgetActivePythonRun"].includes(name)) return;
    if (name === "getPythonRun") return Promise.resolve(structuredClone(run));
    if (name === "resumePythonReviewedPlan") {
      run = { ...run, status: "running", execution_context: {
        __aura_tool_output_review__: { enabled: true, execute_reviewed_plan: true },
      } };
      return Promise.resolve({ id: "saved", status: "running" });
    }
    throw new Error(`Unexpected API call: ${name}`);
  } };
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(MemoryRouter, {
      initialEntries: [{ pathname: "/", state: { openHistory: entry === "history" } }],
      future: { v7_startTransition: true, v7_relativeSplatPath: true },
    }, React.createElement(Demo))));
    if (entry === "history") await act(async () => Simulate.click([...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Open saved workflow")));
    await waitUntil(() => calls.some((call) => call.name === "resumePythonReviewedPlan"));
    assert.match(container.textContent, /Running your workflow/);
    assert.match(container.textContent, /0\/3/);
    assert.doesNotMatch(container.textContent, /Open action preview|Execution paused for approval|Edit .* result/);
    assert.equal(container.querySelector('[aria-label="Tool output checkpoint"]'), null);
    run = { ...run, status: "awaiting_approval", tool_output_review: {
      step_id: "draft", step_ids: ["draft"], tool_slug: "anthropic", operation: "anthropic.chat",
      next_tool_slug: "google-sheets", next_operation: "sheets.create",
    }, steps: [{ ...steps[0], status: "completed", approval_status: "approved", output: {
      tool: "anthropic", operation: "anthropic.chat",
      critic: { action: "accept" }, outcome_check: { status: "verified" },
      provider_result: { ret: { content: [{ type: "text", text: "Completed KPI layout" }] } },
    } }, ...steps.slice(1)] };
    await waitUntil(() => container.querySelector('[aria-label="Tool output checkpoint"]'));
    assert.match(container.textContent, /finished · review result/);
    assert.match(container.textContent, /1\/3/);
    assert.match(container.textContent, /Edit Claude result/);
    assert.doesNotMatch(container.textContent, /Open action preview|Execution paused for approval/);
    assert.equal(calls.filter((call) => call.name === "resumePythonReviewedPlan").length, 1);
    assert.equal(calls.some((call) => ["approvePythonPlan", "decidePythonApproval", "reviewPythonToolOutput"].includes(call.name)), false);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
