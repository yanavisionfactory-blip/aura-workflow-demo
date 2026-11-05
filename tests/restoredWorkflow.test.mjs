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
            && !/\/(ExecutionView|ToolOutputReview|EditRunReviewModal)(\.jsx)?$/.test(id)) {
          return `\0shell:${path.basename(id).replace(/\.jsx$/, "")}`;
        }
      },
      load(id) {
        if (id === "\0saved-run-api") return apiExports.map((name) =>
          `export const ${name} = (...args) => globalThis.__savedRunHarness.api(${JSON.stringify(name)}, args);`).join("\n");
        if (id === "\0saved-run-history") return `export const aura = { entities: {
          WorkflowRun: { filter: async () => [{id: "history", workflow_id: "workflow"}] }
        }, integrations: { Core: { InvokeLLM: (...args) => globalThis.__savedRunHarness.model(...args) } } };`;
        if (id === "\0no-live-planner") return "export const base44 = {};";
        if (id === "\0no-connections") return "export const connectTool = () => { throw new Error('Unexpected connection'); };";
        if (id === "\0instant-motion") return `import React from "react";
          export const AnimatePresence = ({children}) => children;
          const plain = (tag) => ({initial, animate, exit, transition, whileHover, whileTap, ...props}) => React.createElement(tag, props);
          export const motion = { div: plain("div"), button: plain("button") };`;
        if (id === "\0shell:WorkspaceShell") return `import React from "react";
          export default ({children}) => React.createElement("div", null, children);`;
        if (id === "\0shell:HistoryPanel") return `import React from "react";
          export default ({open, onOpenRun, onEditRun}) => open && React.createElement("div", null,
            React.createElement("button", { onClick: () => onOpenRun("saved") }, "Open saved workflow"),
            React.createElement("button", { onClick: () => onEditRun(globalThis.__savedRunHarness.workflow, "writes") }, "Edit and run again"));`;
        if (id === "\0shell:PlanView") return `import React from "react";
          export default ({plan, onApprove, approveLabel, onRetryPlan, busy}) => React.createElement("section", null,
            React.createElement("p", null, plan.error || plan.compileError || plan.interpretation),
            React.createElement("button", { disabled: busy || plan.provisional,
              onClick: () => onApprove(plan.steps, plan.workflowName) }, approveLabel),
            plan.compileState === "blocked" && React.createElement("button", {onClick: onRetryPlan}, "Retry planning"));`;
        if (id === "\0shell:ResultsView") return `import React from "react";
          export default ({results}) => React.createElement("section", { "aria-label": "Finished workflow" }, results.title);`;
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
  for (let attempt = 0; attempt < 200; attempt++) {
    if (predicate()) return;
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  }
  assert.ok(predicate(), "workflow did not reach the expected visible state");
};

for (const failFirst of [false, true]) test(`history edit compiles a fresh durable run before approval${failFirst ? " after a failed planning attempt" : ""}`, async () => {
  const calls = [];
  const prompt = "Create a Plantea KPI dashboard template for September 2026 in Google Sheets, compared to dermalogica.com and bskincaretx.com. Leave unknown actuals blank.";
  const step = { key: "sheet", tool_slug: "google-sheets", operation: "sheets.append", consequential: true,
    arguments: { spreadsheet_id: "existing", range: "Dashboard!A1", values: [["Metric", "Target", "Actual"]] },
    reason: "Write the dashboard", expected_output: "Saved dashboard" };
  const workflow = { id: "workflow", name: "Plantea dashboard", prompt,
    interpretation: "Create a dashboard", steps: [{ tool: "Google Sheets", action: "Old display step" }] };
  let finishPlanning, creations = 0;
  let run = { id: "new-durable-run", status: "awaiting_approval", plan_approved: false,
    prompt, plan: { name: workflow.name, interpretation: prompt, steps: [step] }, steps: [] };
  globalThis.__savedRunHarness = { workflow, api(name, args) {
    calls.push({ name, args });
    if (["rememberedActivePythonRun", "rememberActivePythonRun", "forgetActivePythonRun"].includes(name)) return null;
    if (name === "createPythonRun") {
      creations++;
      if (failFirst && creations === 1) return Promise.reject(Object.assign(new Error("Planning unavailable"), { status: 422 }));
      return new Promise((resolve) => { finishPlanning = () => resolve({ id: run.id }); });
    }
    if (name === "getPythonRun") return Promise.resolve(structuredClone(run));
    if (name === "approvePythonPlan") {
      assert.equal(args[0], "new-durable-run");
      run = { ...run, plan_approved: true, status: "running", steps: [{ ...step, id: "sheet", position: 0, status: "running" }] };
      return Promise.resolve({ id: run.id, status: "running" });
    }
    throw new Error(`Unexpected API call: ${name}`);
  } };
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  try {
    await act(async () => root.render(React.createElement(MemoryRouter, {
      initialEntries: [{ pathname: "/", state: { openHistory: true } }],
      future: { v7_startTransition: true, v7_relativeSplatPath: true },
    }, React.createElement(Demo))));
    await act(async () => Simulate.click(button("Edit and run again")));
    if (failFirst) {
      await waitUntil(() => button("Retry planning"));
      assert.match(container.textContent, /Planning unavailable/);
      assert.equal(button("Review changes").disabled, true);
      assert.equal(button("Run with changes"), undefined);
      await act(async () => Simulate.click(button("Retry planning")));
    }
    await waitUntil(() => finishPlanning);
    assert.equal(button("Review changes").disabled, true);
    assert.equal(button("Run with changes"), undefined);
    assert.equal(calls.some((call) => call.name === "approvePythonPlan"), false);
    const creation = calls.filter((call) => call.name === "createPythonRun").at(-1);
    assert.equal(creation.args[0], prompt, "the short interpretation must not discard company, month or competitors");
    assert.equal(creation.args[3].saved_workflow_id, workflow.id);
    await act(async () => finishPlanning());
    await waitUntil(() => !button("Review changes").disabled);
    await act(async () => Simulate.click(button("Review changes")));
    assert.ok(button("Run with changes"));
    assert.equal(calls.some((call) => call.name === "approvePythonPlan"), false);
    await act(async () => Simulate.click(button("Run with changes")));
    await waitUntil(() => container.textContent.includes("Running your workflow"));
    assert.equal(creations, failFirst ? 2 : 1, "confirmation approves the reviewed run without replanning");
    assert.deepEqual(calls.filter((call) => call.name === "approvePythonPlan").map((call) => call.args), [
      ["new-durable-run", null, false, { reviewToolOutputs: true, executeReviewedPlan: true, reviewBetweenTools: false }],
    ]);
    assert.doesNotMatch(container.textContent, /not attached to a durable/);
  } finally {
    await act(async () => root.unmount()); container.remove();
  }
});

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
    await waitUntil(() => calls.some((call) => call.name === "resumePythonReviewedPlan")
      && container.textContent.includes("Running your workflow"));
    assert.match(container.textContent, /Running your workflow/);
    assert.match(container.textContent, /0\/3/);
    assert.doesNotMatch(container.textContent, /Open action preview|Execution paused for approval|Edit .* result/);
    assert.equal(container.querySelector('[aria-label="Tool result review"]'), null);
    run = { ...run, status: "awaiting_approval", tool_output_review: {
      step_id: "draft", step_ids: ["draft"], tool_slug: "anthropic", operation: "anthropic.chat",
      next_tool_slug: "google-sheets", next_operation: "sheets.create",
    }, steps: [{ ...steps[0], status: "completed", approval_status: "approved", output: {
      tool: "anthropic", operation: "anthropic.chat",
      critic: { action: "accept" }, outcome_check: { status: "verified" },
      provider_result: { ret: { content: [{ type: "text", text: "Completed KPI layout" }] } },
    } }, ...steps.slice(1)] };
    await waitUntil(() => container.querySelector('[aria-label="Tool result review"]'));
    assert.match(container.textContent, /Review Claude result/);
    assert.match(container.textContent, /Completed KPI layout/);
    assert.equal(container.querySelector('[aria-label="Execution steps"]'), null);
    assert.match(container.textContent, /Edit manually/);
    assert.match(container.textContent, /Edit with AI/);
    assert.doesNotMatch(container.textContent, /Preview Claude|Continue to|Open action preview|Execution paused for approval/);
    assert.equal(calls.filter((call) => call.name === "resumePythonReviewedPlan").length, 1);
    assert.equal(calls.some((call) => ["approvePythonPlan", "decidePythonApproval", "reviewPythonToolOutput"].includes(call.name)), false);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test("each tool opens its result automatically; one approval resumes execution and final approval finishes", async () => {
  const calls = [];
  const steps = [
    { id: "draft", key: "draft", position: 0, tool_slug: "anthropic", operation: "anthropic.chat", status: "running" },
    { id: "sheet", key: "sheet", position: 1, tool_slug: "google-sheets", operation: "sheets.append", status: "pending" },
  ].map((step) => ({ ...step, arguments: {}, approval_status: "approved" }));
  let run = { id: "saved", plan_approved: true, status: "running", prompt: "Create a KPI dashboard",
    plan: { name: "Dashboard", steps }, steps, execution_context: {
      __aura_tool_output_review__: { enabled: true, execute_reviewed_plan: true },
    } };
  let resolveApproval;
  let rejectApproval;
  globalThis.__savedRunHarness = { api(name, args) {
    calls.push({ name, args });
    if (name === "rememberedActivePythonRun") return "saved";
    if (["rememberActivePythonRun", "forgetActivePythonRun"].includes(name)) return;
    if (name === "getPythonRun") return Promise.resolve(structuredClone(run));
    if (name === "reviewPythonToolOutput") return new Promise((resolve, reject) => {
      resolveApproval = resolve; rejectApproval = reject;
    });
    throw new Error(`Unexpected API call: ${name}`);
  } };
  const container = document.createElement("div"); document.body.append(container);
  let root = createRoot(container);
  const mount = () => root.render(React.createElement(MemoryRouter, {
    future: { v7_startTransition: true, v7_relativeSplatPath: true },
  }, React.createElement(Demo)));
  const button = (label) => [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  const approvals = () => calls.filter((call) => call.name === "reviewPythonToolOutput");
  try {
    await act(async () => mount());
    await waitUntil(() => container.querySelector('[aria-label="Execution steps"]'));
    run = { ...run, status: "awaiting_approval", tool_output_review: {
      step_id: "draft", step_ids: ["draft"], tool_slug: "anthropic", operation: "anthropic.chat",
      next_tool_slug: "google-sheets", next_operation: "sheets.append",
    }, steps: [{ ...steps[0], status: "completed", output: {
      tool: "anthropic", operation: "anthropic.chat", critic: { action: "accept" }, outcome_check: { status: "verified" },
      provider_result: { ret: { content: [{ type: "text", text: "Completed KPI layout" }] } },
    } }, steps[1]] };
    await waitUntil(() => button("Approve result"));
    assert.match(container.textContent, /Completed KPI layout/);
    assert.equal(container.querySelector('[aria-label="Execution steps"]'), null);
    assert.equal(approvals().length, 0);

    // Reloading a durable checkpoint opens its result, without replaying any tool.
    await act(async () => root.unmount());
    root = createRoot(container);
    await act(async () => mount());
    await waitUntil(() => button("Approve result"));
    assert.match(container.textContent, /Completed KPI layout/);
    assert.equal(approvals().length, 0);
    assert.doesNotMatch(container.textContent, /Preview Claude|Continue to|Open action preview/);

    await act(async () => Simulate.click(button("Edit manually")));
    await act(async () => Simulate.change(container.querySelector("textarea"), { target: { value: "Reviewed KPI layout" } }));
    await act(async () => { Simulate.click(button("Approve result")); Simulate.click(button("Approve result")); });
    assert.equal(approvals().length, 1, "double clicks cannot approve twice");
    assert.equal(button("Approving…").disabled, true);
    await act(async () => rejectApproval(new Error("Temporary save failure")));
    assert.match(container.querySelector('[role="alert"]').textContent, /Temporary save failure/);
    assert.equal(container.querySelector("textarea").value, "Reviewed KPI layout");
    assert.equal(container.querySelector('[aria-label="Execution steps"]'), null);

    globalThis.__savedRunHarness.model = async (request) => {
      assert.match(request.prompt, /Reviewed KPI layout/);
      assert.match(request.prompt, /Include conversions/);
      return { text: "AI-reviewed KPI layout", summary: "Included conversions." };
    };
    await act(async () => Simulate.click(button("Edit with AI")));
    await act(async () => Simulate.change(container.querySelector("form textarea"), { target: { value: "Include conversions" } }));
    await act(async () => Simulate.submit(container.querySelector("form")));
    assert.match(container.textContent, /AI-reviewed KPI layout/);
    assert.equal(approvals().length, 1, "AI editing must not approve or resume a run");
    await act(async () => Simulate.click(button("Approve result")));
    assert.deepEqual(approvals().map((call) => call.args), [
      ["saved", "draft", { draft: "Reviewed KPI layout" }], ["saved", "draft", { draft: "AI-reviewed KPI layout" }],
    ]);
    run = { ...run, status: "running", tool_output_review: null,
      steps: [run.steps[0], { ...steps[1], status: "running" }] };
    await act(async () => resolveApproval({ status: "running" }));
    await waitUntil(() => container.querySelector('[aria-label="Execution steps"]'));
    assert.equal(container.querySelector('[aria-label="Tool result review"]'), null);
    assert.match(container.textContent, /1\/2/);

    run = { ...run, status: "awaiting_approval", tool_output_review: {
      step_id: "sheet", step_ids: ["sheet"], tool_slug: "google-sheets", operation: "sheets.append", is_final: true,
    }, steps: [run.steps[0], { ...steps[1], status: "completed", output: {
      tool: "google-sheets", operation: "sheets.append", critic: { action: "accept" },
      provider_result: { spreadsheetId: "test-dashboard", updates: { updatedRange: "KPIs!A1:C2" } },
      outcome_check: { status: "verified", observed: { spreadsheetId: "test-dashboard", sheets: [{
        properties: { title: "KPIs", sheetId: 0 }, data: [{ rowData: [
          { values: [{ effectiveValue: { stringValue: "Metric" } }, { effectiveValue: { stringValue: "Target" } }, { effectiveValue: { stringValue: "Actual" } }] },
          { values: [{ effectiveValue: { stringValue: "Revenue" } }] },
        ] }] } ] } },
    } }] };
    await waitUntil(() => button("Approve and finish"));
    assert.match(container.textContent, /Review Google Sheets result/);
    assert.match(container.textContent, /Revenue/);
    assert.equal(container.querySelector('[aria-label="Execution steps"]'), null);
    assert.equal(container.querySelector("textarea"), null);
    assert.doesNotMatch(container.textContent, /Completed KPI layout|Preview Google Sheets|Continue to/);
    assert.equal(approvals().length, 2, "the next tool also waits for explicit approval");
    await act(async () => Simulate.click(button("Approve and finish")));
    assert.deepEqual(approvals().at(-1).args, ["saved", "sheet", null]);
    run = { ...run, status: "completed", tool_output_review: null,
      result: { outputs: run.steps.map((step) => ({ ...step.output, step_id: step.id, step_key: step.key })),
        unified_deliverable: { next_steps: ["Review next month’s KPIs"] } } };
    await act(async () => resolveApproval({ status: "running" }));
    await waitUntil(() => container.querySelector('[aria-label="Finished workflow"]'));
    assert.equal(container.querySelector('[aria-label="Tool result review"]'), null);
    assert.equal(calls.some((call) => ["approvePythonPlan", "decidePythonApproval", "resumePythonReviewedPlan"].includes(call.name)), false);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
