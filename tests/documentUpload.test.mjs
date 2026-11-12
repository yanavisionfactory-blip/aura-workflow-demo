import test, { before, after, afterEach } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";
import { JSDOM } from "jsdom";
import React, { act } from "react";

const repo = fileURLToPath(new URL("../", import.meta.url));
const navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
let temporary, dom, fixture, createRoot, Simulate, originalUpload;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".document-upload-"));
  const exportsOf = (name) => [...fs.readFileSync(path.join(repo, `src/lib/${name}.js`), "utf8")
    .matchAll(/^export (?:async )?(?:function|const) (\w+)/gm)].map((match) => match[1]);
  await build({ configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: { alias: [
      { find: "@/api/base44Client", replacement: "\0upload-history" },
      { find: "@/lib/auraApi", replacement: "\0upload-api" },
      { find: "@/lib/connectService", replacement: "\0upload-connections" },
      { find: "framer-motion", replacement: "\0upload-motion" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "document-upload-test", enforce: "pre", load(id) {
      if (id === "\0upload-history") return "export const base44 = {entities:{WorkflowRun:{list:async()=>[]}}};";
      if (id === "\0upload-api") return exportsOf("auraApi").map((name) => `export const ${name} = async () => [];`).join("\n");
      if (id === "\0upload-connections") return exportsOf("connectService").map((name) => `export const ${name} = async () => (${name === "hydrateConnections" ? "[]" : "{}"});`).join("\n");
      if (id === "\0upload-motion") return `import React from "react";
        export const AnimatePresence = ({children}) => children;
        const plain = (tag) => ({initial, animate, exit, transition, whileHover, whileTap, ...props}) => React.createElement(tag, props);
        export const motion = Object.fromEntries(["div","button","span","aside","h1","p"].map(tag=>[tag,plain(tag)]));`;
    } }],
    build: { ssr: path.join(repo, "tests/fixtures/documentUpload.jsx"), outDir: temporary,
      emptyOutDir: true, copyPublicDir: false, rollupOptions: { output: { entryFileNames: "upload.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  process.env.NODE_ENV = "test";
  dom = new JSDOM("<!doctype html><body></body>", { pretendToBeVisual: true, url: "https://aura.example.invalid" });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
    FileReader: dom.window.FileReader, IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  ({ createRoot } = await import("react-dom/client"));
  ({ Simulate } = await import("react-dom/test-utils"));
  fixture = await import(pathToFileURL(path.join(temporary, "upload.mjs")));
  originalUpload = fixture.aura.integrations.Core.UploadFile;
});
afterEach(() => {
  fixture.aura.integrations.Core.UploadFile = originalUpload;
  fixture.getAttachedDocuments().forEach((doc) => fixture.removeDocument(doc.file_url, doc.name));
});
after(() => {
  dom?.window.close();
  for (const key of ["window", "document", "localStorage", "FileReader", "IS_REACT_ACT_ENVIRONMENT"]) delete globalThis[key];
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else delete globalThis.navigator;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});
const file = (name, text = "Metric,Target,Actual\nRevenue,,") => new dom.window.File([text], name, { type: "text/csv" });
const button = (container, label) => [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === label);
const waitUntil = async (predicate) => {
  for (let i = 0; i < 100 && !predicate(); i++) await act(async () => new Promise((resolve) => setTimeout(resolve, 10)));
  assert.ok(predicate(), "attachment did not reach the expected state");
};
async function mounted(component, run) {
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container);
  try { await act(async () => root.render(component)); await run(container, root); }
  finally { await act(async () => root.unmount()); container.remove(); }
}
async function drop(container, files, items = []) {
  let prevented = false;
  const dataTransfer = { files, items, types: ["Files"] };
  await act(async () => Simulate.drop(container.querySelector('[aria-label="Document upload"]'), {
    dataTransfer, preventDefault: () => { prevented = true; }, stopPropagation() {},
  }));
  assert.equal(prevented, true, "a file drop must not navigate the browser away");
}

test("dropping multiple documents in the prompt keeps the batch visible and submits their contents", async () => {
  const submissions = [];
  let releaseUpload;
  const ready = new Promise((resolve) => { releaseUpload = resolve; });
  fixture.aura.integrations.Core.UploadFile = async (args) => { await ready; return originalUpload(args); };
  await mounted(React.createElement(fixture.CommandInput, { examples: [], initialValue: "Create a KPI dashboard",
    enableWeeklyReviewSetup: false, onSubmit: (...args) => submissions.push(args) }), async (container) => {
    await act(async () => Simulate.click(button(container, "tools, docs & agents")));
    await act(async () => Simulate.click(button(container, "Documents")));
    const target = container.querySelector('[aria-label="Document upload"]');
    const transfer = { types: ["Files"], files: [] };
    let prevented = false;
    await act(async () => Simulate.dragEnter(target, { dataTransfer: transfer }));
    await act(async () => Simulate.dragOver(target, { dataTransfer: transfer, preventDefault: () => { prevented = true; } }));
    assert.equal(prevented, true); assert.equal(transfer.dropEffect, "copy");
    assert.match(container.textContent, /Drop files here/);
    await drop(container, [file("targets.csv"), file("actuals.csv", "Revenue,150")]);
    assert.equal(button(container, "Create plan").disabled, true);
    await act(async () => Simulate.keyDown(container.querySelector("textarea"), { key: "Enter" }));
    assert.equal(submissions.length, 0, "planning waits until all selected files have attached");
    await act(async () => releaseUpload());
    await waitUntil(() => fixture.getAttachedDocuments().length === 2);
    assert.ok(container.querySelector('[aria-label="Document upload"]'), "keep the composer open for all files");
    assert.match(container.textContent, /targets.csv/); assert.match(container.textContent, /actuals.csv/);
    await act(async () => Simulate.click(button(container, "Create plan")));
    const docs = submissions[0][2].documents;
    assert.deepEqual(docs.map((doc) => doc.name), ["targets.csv", "actuals.csv"]);
    assert.match(Buffer.from(docs[1].file_url.split(",")[1], "base64").toString(), /Revenue,150/);
  });
});

test("the Connect documents panel shares drag-and-drop and the prompt attachment store", async () => {
  await mounted(React.createElement(fixture.ConnectionsPill), async (container) => {
    await act(async () => Simulate.click(container.querySelector("button")));
    await act(async () => Simulate.click(button(container, "Attach docs")));
    await drop(container, [file("connected-input.csv")]);
    await waitUntil(() => fixture.getAttachedDocuments().length === 1);
    assert.match(container.textContent, /connected-input.csv/);
    assert.equal(fixture.getAttachedDocuments()[0].name, "connected-input.csv");
  });
});

test("picker and drop share count/size validation, reject folders, and allow retry after a read failure", async () => {
  const attached = [], uploaded = [];
  fixture.aura.integrations.Core.UploadFile = async ({file: chosen}) => {
    uploaded.push(chosen.name);
    if (uploaded.length === 1) throw new Error("Could not read the selected file");
    return { file_url: "data:text/csv;base64,QQ==" };
  };
  const props = { documents: Array(7).fill({ name: "existing" }), onAttach: (doc) => attached.push(doc) };
  await mounted(React.createElement(fixture.DocumentUpload, props), async (container, root) => {
    await drop(container, [file("a.csv"), file("b.csv")]);
    assert.match(container.querySelector('[role="alert"]').textContent, /eight/);
    assert.deepEqual(uploaded, []);
    await act(async () => root.render(React.createElement(fixture.DocumentUpload, { ...props, documents: [] })));
    await drop(container, [{ name: "large.pdf", size: 10 * 1024 * 1024 + 1 }]);
    assert.match(container.querySelector('[role="alert"]').textContent, /10 MB/);
    await drop(container, [], [{ kind: "file", webkitGetAsEntry: () => ({ isDirectory: true }) }]);
    assert.match(container.querySelector('[role="alert"]').textContent, /instead of folders/);
    const input = container.querySelector('input[type="file"]');
    assert.equal(input.multiple, true);
    const target = { files: [file("retry.csv")], value: "previous choice" };
    await act(async () => Simulate.change(input, { target }));
    assert.equal(target.value, "", "reset the picker so the same file can be selected again");
    assert.match(container.querySelector('[role="alert"]').textContent, /Could not read/);
    await act(async () => Simulate.change(input, { target }));
    assert.deepEqual(attached.map((doc) => doc.name), ["retry.csv"]);
    assert.equal(container.querySelector('[role="alert"]'), null);
  });
});

test("concurrent drops cannot duplicate a pending upload and one failed file does not lose the rest", async () => {
  const attached = [], calls = [];
  let resolve;
  fixture.aura.integrations.Core.UploadFile = ({file: chosen}) => {
    calls.push(chosen.name);
    if (calls.length === 1) return new Promise((done) => { resolve = done; });
    if (chosen.name === "bad.csv") return Promise.reject(new Error("Read failed"));
    return Promise.resolve({ file_url: `data:text/csv,${chosen.name}` });
  };
  await mounted(React.createElement(fixture.DocumentUpload, { onAttach: (doc) => attached.push(doc) }), async (container) => {
    await drop(container, [file("first.csv"), file("bad.csv"), file("last.csv")]);
    await drop(container, [file("duplicate.csv")]);
    assert.deepEqual(calls, ["first.csv"]);
    assert.equal(container.querySelector("button").disabled, true);
    await act(async () => resolve({ file_url: "data:text/csv,first" }));
    assert.deepEqual(attached.map((doc) => doc.name), ["first.csv", "last.csv"]);
    assert.match(container.querySelector('[role="alert"]').textContent, /bad.csv: Read failed/);
    assert.equal(container.querySelector("button").disabled, false);
  });
});


test("an empty prompt exposes video drop and picker; actual bytes reach plan inputs", async () => {
  const submissions = [];
  await mounted(React.createElement(fixture.CommandInput, { examples: [],
    enableWeeklyReviewSetup: false, onSubmit: (...args) => submissions.push(args) }), async (container) => {
    assert.match(container.textContent, /Drop video or files here, or browse/);
    assert.ok(container.querySelector('input[type="file"]'));
    const video = new dom.window.File([new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112])],
      "production.mp4", { type: "video/mp4" });
    await drop(container, [video]);
    await waitUntil(() => fixture.getAttachedDocuments().length === 1);
    assert.match(container.textContent, /production.mp4/);
    await act(async () => Simulate.change(container.querySelector("textarea"), {
      target: { value: "Review this video with timestamps and corrections" },
    }));
    await act(async () => Simulate.click(button(container, "Create plan")));
    const attached = submissions[0][2].documents[0];
    assert.equal(attached.name, "production.mp4");
    assert.equal(attached.size, 8);
    assert.equal(attached.file_url, "data:video/mp4;base64,AAAAGGZ0eXA=");
  });
});

test("a disabled prompt cannot accept files through drop or picker", async () => {
  await mounted(React.createElement(fixture.CommandInput, { examples: [], disabled: true,
    enableWeeklyReviewSetup: false, onSubmit() {} }), async (container) => {
    assert.equal(container.querySelector('input[type="file"]').disabled, true);
    await drop(container, [file("blocked.csv")]);
    assert.equal(fixture.getAttachedDocuments().length, 0);
  });
});
