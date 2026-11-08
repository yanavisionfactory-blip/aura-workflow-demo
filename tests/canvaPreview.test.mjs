import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";
import { JSDOM } from "jsdom";
import React, { act } from "react";

const repo = fileURLToPath(new URL("../", import.meta.url));
let temporary, dom, CanvaResult, createRoot;
const result = { designId: "saved", title: "Comparison", sourceStepKey: "verified", thumbnailUrl: "https://media.canva.com/expired.jpg" };
const fresh = { designId: "saved", thumbnailUrl: "https://media.canva.com/fresh.jpg", link: "https://www.canva.com/design/saved/edit" };
async function waitFor(condition) {
  for (let attempt = 0; attempt < 100 && !condition(); attempt++) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  }
  assert.ok(condition(), "Expected preview state did not appear");
}
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".canva-preview-"));
  await build({ configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: { alias: [{ find: "@/lib/auraApi", replacement: "\0canva-api" }, { find: "@", replacement: path.join(repo, "src") }] },
    plugins: [{ name: "mock-canva-read", load(id) { if (id === "\0canva-api") return "export const auraRequest = (...args) => globalThis.__canvaRead(...args);"; } }],
    build: { ssr: path.join(repo, "src/components/aura/CanvaResult.jsx"), outDir: temporary, emptyOutDir: true,
      rollupOptions: { output: { entryFileNames: "canva.mjs" } } },
  });
  dom = new JSDOM("<!doctype html><body></body>");
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, IS_REACT_ACT_ENVIRONMENT: true });
  ({ createRoot } = await import("react-dom/client"));
  ({ default: CanvaResult } = await import(pathToFileURL(path.join(temporary, "canva.mjs"))));
});
after(() => {
  dom?.window.close();
  for (const name of ["window", "document", "IS_REACT_ACT_ENVIRONMENT", "__canvaRead"]) delete globalThis[name];
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});
async function mount(read, callback) {
  globalThis.__canvaRead = read;
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(React.createElement(CanvaResult, { result, backendRunId: "original-run", onCanvaScreen: callback })));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return { container, root, close: async () => { await act(async () => root.unmount()); container.remove(); } };
}

test("a saved report refreshes an expired thumbnail and native editor link without running the workflow", async () => {
  const calls = [], screens = [];
  const ui = await mount(async (...args) => { calls.push(args); return fresh; }, (screen) => screens.push(screen));
  try {
    await waitFor(() => ui.container.querySelector("img")?.src === fresh.thumbnailUrl);
    assert.equal(ui.container.querySelector("img").src, fresh.thumbnailUrl);
    assert.equal(ui.container.querySelector("details"), null);
    assert.deepEqual(calls, [["/v1/runs/original-run/steps/verified/canva-screen", { timeoutMs: 25000 }]]);
    assert.deepEqual(screens, [fresh]);
  } finally { await ui.close(); }
});

test("image failure automatically retries only once and keeps a manual recovery button", async () => {
  let calls = 0;
  const ui = await mount(async () => { calls++; return fresh; });
  try {
    await waitFor(() => ui.container.querySelector("img")?.src === fresh.thumbnailUrl);
    await act(async () => ui.container.querySelector("img").dispatchEvent(new window.Event("error")));
    await waitFor(() => calls === 2 && ui.container.querySelector("img"));
    await act(async () => ui.container.querySelector("img").dispatchEvent(new window.Event("error")));
    await waitFor(() => ui.container.querySelector("button"));
    assert.equal(calls, 2);
    assert.match(ui.container.textContent, /Retry Canva preview/);
    assert.doesNotMatch(ui.container.textContent, /presentation is ready/);
    await act(async () => ui.container.querySelector("button").click());
    await waitFor(() => calls === 3 && ui.container.querySelector("img"));
    assert.equal(calls, 3);
    assert.ok(ui.container.querySelector("img"));
  } finally { await ui.close(); }
});

test("mismatched designs and unsafe media never replace the saved preview", async () => {
  for (const response of [{ ...fresh, designId: "other" }, { ...fresh, thumbnailUrl: "https://canva.com.evil.example/image" }]) {
    const screens = [];
    const ui = await mount(async () => response, (screen) => screens.push(screen));
    try {
      await waitFor(() => ui.container.querySelector("button"));
      assert.equal(ui.container.querySelector("img").src, result.thumbnailUrl);
      assert.match(ui.container.textContent, /Retry Canva preview/);
      assert.deepEqual(screens, []);
    } finally { await ui.close(); }
  }
});

test("late preview responses do not change another report after unmount", async () => {
  let resolve;
  const screens = [];
  const ui = await mount(() => new Promise((done) => { resolve = done; }), (screen) => screens.push(screen));
  await ui.close();
  await act(async () => resolve(fresh));
  assert.deepEqual(screens, []);
});
