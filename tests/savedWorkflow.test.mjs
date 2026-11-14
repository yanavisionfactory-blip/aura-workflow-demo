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
async function waitForText(container, text) {
  for (let i = 0; i < 100; i++) {
    if (text.test(container.textContent)) return;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
  }
  assert.match(container.textContent, text);
}
const mocks = {
  "@/lib/AuthContext": "export const useAuth = () => globalThis.__draft.auth;",
  "@/lib/auraApi": "export const getPythonWorkflow = (...args) => globalThis.__draft.read(...args); export const createPythonRun = (...args) => globalThis.__draft.create(...args);",
  "@/components/aura/WorkspaceShell": "export default ({children}) => children;",
};
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".draft-test-"));
  await build({ configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: {alias: [...Object.keys(mocks).map(find => ({find, replacement: `\0mock:${find}`})),
      {find: "@", replacement: path.join(repo, "src")}]},
    plugins: [{name: "draft-test", load(id) { if (id.startsWith("\0mock:")) return mocks[id.slice(6)]; }}],
    build: {ssr: path.join(repo, "tests/fixtures/savedWorkflow.jsx"), outDir: temporary, emptyOutDir: true,
      rollupOptions: {output: {entryFileNames: "draft.mjs"}}},
  });
  dom = new JSDOM("<!doctype html><body></body>");
  Object.assign(globalThis, {window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true});
  ({createRoot} = await import("react-dom/client"));
  ui = await import(pathToFileURL(path.join(temporary, "draft.mjs")));
});
after(() => {
  dom?.window.close();
  for (const name of ["window", "document", "IS_REACT_ACT_ENVIRONMENT", "__draft"]) delete globalThis[name];
  if (temporary) fs.rmSync(temporary, {recursive: true, force: true});
});
const task = {id: "visa", name: "Visa documents", prompt: "Read Виза 💖 / Германия and create slides", enabled: false};
async function renderTask(action) {
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  let destination;
  const Plan = () => { destination = ui.useLocation(); return React.createElement("p", null, "Review plan"); };
  const render = () => root.render(React.createElement(ui.MemoryRouter, {initialEntries: ["/workflows/visa"],
    future: {v7_startTransition: true, v7_relativeSplatPath: true}},
  React.createElement(ui.Routes, null,
    React.createElement(ui.Route, {path: "/workflows/:workflowId", element: React.createElement(ui.SavedWorkflow)}),
    React.createElement(ui.Route, {path: "/", element: React.createElement(Plan)}))));
  try {
    await act(async () => render());
    await action({container, render, destination: () => destination});
  } finally { await act(async () => root.unmount()); container.remove(); }
}

test("opening a saved task waits for workspace and never starts it", async () => {
  const calls = [];
  globalThis.__draft = {auth: {workspace: null, isLoadingWorkspace: true}, read: async id => {
    calls.push(id); return {...task};
  }, create: () => {throw new Error("Opening a link must not create a run");}};
  await renderTask(async ({container, render}) => {
    assert.deepEqual(calls, []);
    __draft.auth = {workspace: {workspace_id: "a"}};
    await act(async () => render());
    await waitForText(container, /Visa documents/);
    assert.match(container.textContent, /Visa documents/);
    assert.ok(container.textContent.includes(task.prompt));
    assert.deepEqual(calls, ["visa"]);
    assert.equal(container.querySelector("button").textContent, "Build the plan");
  });
});

test("Build the plan preserves the task and starts only one planning request", async () => {
  const creates = []; let resolve;
  globalThis.__draft = {auth: {workspace: {workspace_id: "a"}}, read: async () => ({...task}),
    create: (...args) => {creates.push(args); return new Promise(done => {resolve = done;});}};
  await renderTask(async ({container, destination}) => {
    await waitForText(container, /Visa documents/);
    const button = container.querySelector("button");
    await act(async () => {button.click(); button.click();});
    assert.equal(creates.length, 1);
    assert.deepEqual(creates[0].slice(0, 2), [task.prompt, null]);
    assert.match(creates[0][2], /^[0-9a-f-]{36}$/);
    await act(async () => resolve({id: "new-plan"}));
    await waitForText(container, /Review plan/);
    assert.deepEqual(destination().state, {resumeRunId: "new-plan"});
  });
});

test("an ambiguous planning failure retries the same idempotency key", async () => {
  const keys = [];
  globalThis.__draft = {auth: {workspace: {workspace_id: "a"}}, read: async () => ({...task}),
    create: async (_prompt, _id, key) => {keys.push(key); throw new Error("Lost response");}};
  await renderTask(async ({container}) => {
    await waitForText(container, /Visa documents/);
    await act(async () => container.querySelector("button").click());
    await waitForText(container, /same request/);
    assert.match(container.textContent, /same request/);
    await act(async () => container.querySelector("button").click());
    assert.equal(keys.length, 2); assert.equal(keys[0], keys[1]);
  });
});

test("changing workspace hides the task and ignores late planning results", async () => {
  let resolve;
  globalThis.__draft = {auth: {workspace: {workspace_id: "a"}}, read: async () => {
    if (__draft.auth.workspace.workspace_id === "b") throw Object.assign(new Error("Missing"), {status: 404});
    return {...task};
  }, create: () => new Promise(done => {resolve = done;})};
  await renderTask(async ({container, render, destination}) => {
    await waitForText(container, /Visa documents/);
    await act(async () => container.querySelector("button").click());
    __draft.auth = {workspace: {workspace_id: "b"}};
    await act(async () => render());
    await waitForText(container, /current workspace/);
    assert.doesNotMatch(container.textContent, /Visa documents/);
    assert.match(container.textContent, /current workspace/);
    await act(async () => resolve({id: "old-account-plan"}));
    assert.equal(destination(), undefined);
  });
});
