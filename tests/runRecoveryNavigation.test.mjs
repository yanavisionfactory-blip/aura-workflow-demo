import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";
import { JSDOM } from "jsdom";
import React, { act } from "react";

const repo = fileURLToPath(new URL("../", import.meta.url));
let temporary, dom, ui, createRoot;
const globals = new Map();
const video = { name: "original.mp4", file_url: "data:video/mp4;base64,YWI=", size: 2 };
const prompt = "Review this video from beginning to end with exact timestamps and recommended corrections.";
function failedRun(documents = [video]) {
  const steps = [
    { id: "identity", key: "identity", tool_slug: "frameio", operation: "frameio.identity.get",
      consequential: false, status: "completed", reason: "Check the connected Frame.io account",
      output: { provider_result: { accounts: [] } } },
    { id: "review", key: "review", tool_slug: "frameio", operation: "frameio.video.review",
      consequential: false, status: "failed", reason: "Review the video and prepare production feedback",
      error: "AURA couldn't complete the remaining step automatically.",
      recovery: { reason_code: "frameio_target_invalid" }, output: {} },
  ];
  return { id: "saved", prompt, plan_approved: true, status: "waiting_for_action",
    inputs: { attached_documents: documents }, steps,
    plan: { name: "Review attached Frame.io video", interpretation: prompt, steps },
    blocker: { action: "choose_resource", code: "frameio_target_invalid" } };
}
const apiNames = [...fs.readFileSync(path.join(repo, "src/lib/auraApi.js"), "utf8")
  .matchAll(/^export (?:async )?function (\w+)/gm)].map((match) => match[1]);
const mocks = {
  "@/lib/AuthContext": "export const useAuth = () => globalThis.__recovery.auth;",
  "@/lib/authState.mjs": "export const useOptionalAuth = () => globalThis.__recovery.auth;",
  "@/lib/auraApi": `export const pythonRuntimeEnabled = true;
    export const auraRequest = (...args) => globalThis.__recovery.api("auraRequest", ...args);
    ${apiNames.map((name) => `export const ${name} = (...args) => globalThis.__recovery.api("${name}", ...args);`).join("\n")}`,
  "@/api/auraClient": "export const aura = { integrations: { Core: { InvokeLLM() { throw new Error('Unexpected model call'); } } } };",
  "@/api/base44Client": "export const base44 = {};",
  "@/components/aura/WorkspaceShell": "export default ({children}) => children;",
  "@/components/aura/CommandInput": 'import React from "react"; export default ({initialValue}) => React.createElement("textarea", {readOnly: true, value: initialValue, "aria-label": "Workflow request"});',
  "@/components/aura/PlanView": 'import React from "react"; export default () => React.createElement("p", null, "New plan awaits Start");',
  "framer-motion": `import React from "react";
    const components = {};
    export const motion = new Proxy({}, {get(_, tag) {
      return components[tag] ||= React.forwardRef(({children, initial, animate, exit, transition, whileHover, whileTap, layout, ...props}, ref) => React.createElement(tag, {...props, ref}, children));
    }});
    export const AnimatePresence = ({children}) => children;`,
};
for (const name of ["PilotBuilder", "ConfirmView", "PreviewView", "ExecutionView", "ToolOutputReview", "HistoryPanel", "EditRunReviewModal"]) {
  mocks[`@/components/aura/${name}`] = "export default () => null;";
}
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".recovery-navigation-test-"));
  await build({ configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: { alias: [...Object.keys(mocks).map((find) => ({ find, replacement: `\0mock:${find}` })),
      { find: "@", replacement: path.join(repo, "src") }] },
    plugins: [{ name: "isolated-recovery-navigation", load(id) { if (id.startsWith("\0mock:")) return mocks[id.slice(6)]; } }],
    build: { ssr: path.join(repo, "tests/fixtures/runRecoveryNavigation.jsx"), outDir: temporary, emptyOutDir: true,
      rollupOptions: { output: { entryFileNames: "navigation.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  dom = new JSDOM("<!doctype html><body></body>", { url: "https://aura.example.test/runs/saved/recover" });
  for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document,
    HTMLElement: dom.window.HTMLElement, Element: dom.window.Element, SVGElement: dom.window.SVGElement,
    navigator: dom.window.navigator, IS_REACT_ACT_ENVIRONMENT: true })) {
    globals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  }
  ({ createRoot } = await import("react-dom/client"));
  ui = await import(pathToFileURL(path.join(temporary, "navigation.mjs")));
});
after(() => {
  dom?.window.close();
  for (const [name, descriptor] of globals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor);
    else delete globalThis[name];
  }
  delete globalThis.__recovery;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});

function setup(run = failedRun(), entry = "/runs/saved/recover") {
  const calls = [];
  globalThis.__recovery = {
    auth: { workspace: { workspace_id: "a", name: "A" } },
    api(name, ...args) {
      calls.push([name, ...args]);
      if (name === "getPythonRun") return Promise.resolve(run);
      if (["rememberedActivePythonRun", "rememberActivePythonRun", "forgetActivePythonRun"].includes(name)) return null;
      if (name === "createPythonRun") return Promise.resolve({ id: "new-review", prompt: args[0], status: "awaiting_plan_approval", plan_approved: false,
        inputs: args[3], steps: [], plan: { interpretation: args[0], steps: [
          { key: "review", tool_slug: "aura", operation: "intelligence.video.review", consequential: false, arguments: {} },
        ] } });
      throw new Error(`Unexpected API operation: ${name}`);
    },
  };
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  let location;
  function Location() { location = ui.useLocation(); return null; }
  const render = () => root.render(React.createElement(ui.MemoryRouter, { initialEntries: [entry],
    future: { v7_startTransition: true, v7_relativeSplatPath: true } },
  React.createElement(Location), React.createElement(ui.Routes, null,
    React.createElement(ui.Route, { path: "/runs/:runId", element: React.createElement(ui.SavedRunResults) }),
    React.createElement(ui.Route, { path: "/runs/:runId/recover", element: React.createElement(ui.SavedRunResults, { recovery: true }) }))));
  return { calls, container, render, location: () => location,
    async close() { ui.replaceAttachedDocuments([]); await act(async () => root.unmount()); container.remove(); } };
}
async function waitForText(container, pattern) {
  for (let i = 0; i < 100 && !pattern.test(container.textContent); i++) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  }
  assert.match(container.textContent, pattern);
}
async function click(container, label) {
  const button = [...container.querySelectorAll("button")].find((item) => item.textContent === label);
  assert.ok(button, `Missing button: ${label}`);
  await act(async () => button.click());
}

test("Resolve failed step navigates from real saved results to the real recovery screen", async () => {
  const app = setup(failedRun(), "/runs/saved");
  try {
    await act(async () => app.render());
    await waitForText(app.container, /Resolve failed step/);
    await click(app.container, "Resolve failed step");
    await waitForText(app.container, /Review uploaded video/);
    assert.equal(app.location().pathname, "/runs/saved/recover");
    await waitForText(app.container, /1 of 2 steps already completed/);
    assert.deepEqual(app.calls.filter(([name]) => name === "getPythonRun"), [["getPythonRun", "saved"], ["getPythonRun", "saved"]]);
    assert.deepEqual(app.calls.filter(([name]) => name !== "getPythonRun"), []);
  } finally { await app.close(); }
});

test("direct recovery reload waits for workspace, then restores the exact upload only on explicit recovery", async () => {
  const app = setup();
  __recovery.auth = { workspace: null, isLoadingWorkspace: true };
  try {
    await act(async () => app.render());
    assert.match(app.container.textContent, /Opening workflow recovery/);
    assert.deepEqual(app.calls, []);
    __recovery.auth = { workspace: { workspace_id: "a", name: "A" }, isLoadingWorkspace: false };
    await act(async () => app.render());
    await waitForText(app.container, /Review uploaded video/);
    assert.deepEqual(app.calls, [["getPythonRun", "saved"]]);
    await click(app.container, "Review uploaded video");
    await waitForText(app.container, /New plan awaits Start/);
    const created = app.calls.filter(([name]) => name === "createPythonRun");
    assert.equal(created.length, 1);
    assert.match(created[0][1], new RegExp(prompt.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.deepEqual(created[0][4].attached_documents, [video]);
    assert.ok(!app.calls.some(([name]) => /^(approve|resume|decide|cancel)/.test(name)));
  } finally { await app.close(); }
});

test("a missing saved upload leads to video selection with the original request", async () => {
  const app = setup(failedRun([]));
  try {
    await act(async () => app.render());
    await waitForText(app.container, /Select video for review/);
    await click(app.container, "Select video for review");
    assert.equal(app.container.querySelector("textarea").value, prompt);
    assert.deepEqual(ui.getAttachedDocuments(), []);
    assert.ok(!app.calls.some(([name]) => name === "createPythonRun"));
  } finally { await app.close(); }
});

test("direct recovery displays a failed status read and retries without executing", async () => {
  const app = setup();
  const api = __recovery.api;
  let fail = true;
  __recovery.api = (name, ...args) => name === "getPythonRun" && fail
    ? Promise.reject(new Error("Network unavailable")) : api(name, ...args);
  try {
    await act(async () => app.render());
    await waitForText(app.container, /could not load this workflow/);
    assert.doesNotMatch(app.container.textContent, /Review uploaded video/);
    fail = false;
    await click(app.container, "Retry loading workflow");
    await waitForText(app.container, /Review uploaded video/);
    assert.deepEqual(app.calls, [["getPythonRun", "saved"]]);
  } finally { await app.close(); }
});

for (const status of ["running", "completed"]) {
  test(`opening a recovery URL for a ${status} run does not resume or approve it`, async () => {
    const run = { ...failedRun(), status, steps: [] };
    const app = setup(run);
    try {
      await act(async () => app.render());
      await waitForText(app.container, /Results from every tool|What would you like to do next/);
      assert.doesNotMatch(app.container.textContent, /Review uploaded video/);
      assert.deepEqual(app.calls, [["getPythonRun", "saved"]]);
    } finally { await app.close(); }
  });
}

test("workspace denial stays visible on a recovery URL and never mounts the execution view", async () => {
  const app = setup();
  __recovery.api = () => Promise.reject(Object.assign(new Error("Forbidden"), { status: 403 }));
  try {
    await act(async () => app.render());
    await waitForText(app.container, /not available in your current workspace/);
    assert.doesNotMatch(app.container.textContent, /Review uploaded video|Select video for review/);
  } finally { await app.close(); }
});
