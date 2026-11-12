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
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  }
  assert.match(container.textContent, text);
}
const mocks = {
  "@/lib/AuthContext": "export const useAuth = () => globalThis.__access.auth;",
  "@/lib/authState.mjs": "export const useOptionalAuth = () => globalThis.__access.auth;",
  "@/lib/auraApi": "export const getPythonRun = (...args) => globalThis.__access.read(...args);",
  "@clerk/react": 'import React from "react"; export const UserButton = () => React.createElement("button", null, "Manage account");',
  "@/components/aura/WorkspaceShell": "export default ({children}) => children;",
  "@/pages/Demo": "export default () => null;",
  "@/components/aura/ResultsView": 'import React from "react"; export default ({backendRunId, prompt, onRepeatWorkflow}) => React.createElement("div", null, `Loaded ${backendRunId}`, React.createElement("button", {onClick: () => onRepeatWorkflow(prompt)}, "Run again"));',
};
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".access-test-"));
  await build({ configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: { alias: [...Object.keys(mocks).map((find) => ({find, replacement: `\0mock:${find}`})),
      { find: "@", replacement: path.join(repo, "src") }] },
    plugins: [{name: "isolated-access", load(id) { if (id.startsWith("\0mock:")) return mocks[id.slice(6)]; }}],
    build: {ssr: path.join(repo, "tests/fixtures/savedRunAccess.jsx"), outDir: temporary, emptyOutDir: true,
      rollupOptions: {output: {entryFileNames: "access.mjs"}}},
  });
  dom = new JSDOM("<!doctype html><body></body>");
  Object.assign(globalThis, {window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true});
  ({createRoot} = await import("react-dom/client"));
  ui = await import(pathToFileURL(path.join(temporary, "access.mjs")));
});
after(() => {
  dom?.window.close();
  for (const name of ["window", "document", "IS_REACT_ACT_ENVIRONMENT", "__access"]) delete globalThis[name];
  if (temporary) fs.rmSync(temporary, {recursive: true, force: true});
});

test("saved links wait for authenticated workspace and refetch when the selected workspace changes", async () => {
  const calls = [];
  globalThis.__access = {auth: {workspace: null, isLoadingWorkspace: true}, read: async (id) => {
    const workspace = globalThis.__access.auth.workspace.workspace_id;
    calls.push([id, workspace]);
    if (workspace === "a") throw Object.assign(new Error("Unavailable"), {status: 404});
    return {id, status: "completed", steps: []};
  }};
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  const render = () => root.render(React.createElement(ui.MemoryRouter, {initialEntries: ["/runs/saved"],
    future: {v7_startTransition: true, v7_relativeSplatPath: true}},
  React.createElement(ui.Routes, null, React.createElement(ui.Route, {path: "/runs/:runId", element: React.createElement(ui.SavedRunResults)}))));
  try {
    await act(async () => render());
    assert.deepEqual(calls, []);
    __access.auth = {workspace: {workspace_id: "a", name: "A"}, user: {primaryEmailAddress: {emailAddress: "owner@example.com"}}};
    await act(async () => render());
    await waitForText(container, /current workspace/);
    assert.match(container.textContent, /current workspace/);
    assert.match(container.textContent, /owner@example.com/);
    __access.auth = {...__access.auth, workspace: {workspace_id: "b", name: "B"}};
    await act(async () => render());
    await waitForText(container, /Loaded saved/);
    assert.match(container.textContent, /Loaded saved/);
    assert.deepEqual(calls, [["saved", "a"], ["saved", "b"]]);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("network failures offer retry without falsely claiming workspace denial", async () => {
  let fail = true;
  globalThis.__access = {auth: {workspace: {workspace_id: "a", name: "A"}}, read: async () => {
    if (fail) throw new Error("Network unavailable");
    return {id: "saved", status: "completed", steps: []};
  }};
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(ui.MemoryRouter, {future: {v7_startTransition: true, v7_relativeSplatPath: true}}, React.createElement(ui.SavedRunResults))));
    await waitForText(container, /connection is available/);
    assert.match(container.textContent, /connection is available/);
    assert.doesNotMatch(container.textContent, /does not grant access/);
    fail = false;
    await act(async () => container.querySelector("button").click());
    await waitForText(container, /Loaded saved/);
    assert.match(container.textContent, /Loaded saved/);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

test("Run again from a saved result restores its video and only prefills a fresh request", async () => {
  const video = { name: "original.mp4", file_url: "data:video/mp4;base64,YWI=", size: 2 };
  const prompt = "Review the attached video with timestamps.";
  let reads = 0;
  globalThis.__access = { auth: { workspace: { workspace_id: "a", name: "A" } }, read: async (id) => {
    reads += 1;
    return { id, prompt, status: "waiting_for_action", steps: [], inputs: { attached_documents: [video] } };
  }};
  ui.replaceAttachedDocuments([{ name: "unrelated.txt", file_url: "data:text/plain;base64,YQ==" }]);
  let destination;
  const Input = () => { destination = ui.useLocation(); return React.createElement("p", null, "Fresh input"); };
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(ui.MemoryRouter, { initialEntries: ["/runs/saved"],
      future: { v7_startTransition: true, v7_relativeSplatPath: true } },
    React.createElement(ui.Routes, null,
      React.createElement(ui.Route, { path: "/runs/:runId", element: React.createElement(ui.SavedRunResults) }),
      React.createElement(ui.Route, { path: "/", element: React.createElement(Input) })))));
    await waitForText(container, /Loaded saved/);
    assert.equal(ui.getAttachedDocuments()[0].name, "unrelated.txt"); // Viewing results is read-only.
    await act(async () => [...container.querySelectorAll("button")].find((b) => b.textContent === "Run again").click());
    assert.deepEqual(ui.getAttachedDocuments(), [video]);
    assert.deepEqual(destination.state, { newWorkflow: true, workflowPrompt: prompt });
    assert.equal(reads, 1);
  } finally { ui.replaceAttachedDocuments([]); await act(async () => root.unmount()); container.remove(); }
});

test("account control identifies the signed-in account and offers only listed workspaces", async () => {
  const chosen = [];
  globalThis.__access = {auth: {user: {primaryEmailAddress: {emailAddress: "owner@example.com"}},
    workspace: {workspace_id: "a", name: "A"}, workspaces: [{workspace_id: "a", name: "A"}, {workspace_id: "b", name: "B"}],
    chooseWorkspace: (value) => chosen.push(value)}};
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(ui.WorkspaceIdentity)));
    await act(async () => container.querySelector("button").click());
    assert.match(container.textContent, /owner@example.com/);
    assert.equal(container.querySelectorAll("option").length, 2);
    const select = container.querySelector("select");
    await act(async () => {select.value = "b"; select.dispatchEvent(new window.Event("change", {bubbles: true}));});
    assert.deepEqual(chosen, [{workspace_id: "b", name: "B"}]);
  } finally { await act(async () => root.unmount()); container.remove(); }
});
