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
let temporary, dom, fixture, createRoot;
const catalog = [
  { display_name: "Meta Ads", provider: "meta-ads-direct", canonical_provider: "meta-ads", connection_backend: "native", connectable: true, preferred_connection: true },
  { display_name: "Meta Ads", provider: "meta-ads-mcp", canonical_provider: "meta-ads", connection_backend: "managed_mcp", connectable: true },
];
const pipeboard = { id: "pipeboard", slug: "agent-meta-ads-existing", display_name: "Meta Ads", canonical_provider: "meta-ads",
  connection_backend: "agent_gateway", kind: "mcp", base_url: "https://meta-ads.mcp.pipeboard.co/", enabled: true,
  status: "verified", verification: { ok: true }, is_agent: true, reconnect_supported: true };
const direct = { ...pipeboard, id: "direct", slug: "meta-ads-direct", base_url: "https://graph.facebook.com",
  connection_backend: "meta_direct", kind: "oauth", is_agent: false };

before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".meta-connections-"));
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    define: { "import.meta.env.VITE_AURA_API_URL": JSON.stringify("https://api.example.invalid") },
    resolve: { alias: [
      { find: "framer-motion", replacement: "\0instant-motion" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "meta-connections-test", enforce: "pre", load(id) {
      if (id === "\0instant-motion") return `import React from "react";
        export const AnimatePresence = ({children}) => children;
        const plain = (tag) => ({initial, animate, exit, transition, ...props}) => React.createElement(tag, props);
        export const motion = { div: plain("div"), aside: plain("aside") };`;
    } }],
    build: { ssr: path.join(repo, "tests/fixtures/metaConnections.jsx"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "connections.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  process.env.NODE_ENV = "test";
  dom = new JSDOM("<!doctype html><body></body>", { pretendToBeVisual: true, url: "https://aura.example.invalid/?connect=meta-ads" });
  Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
    Element: dom.window.Element, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
  ({ createRoot } = await import("react-dom/client"));
  fixture = await import(pathToFileURL(path.join(temporary, "connections.mjs")));
  fixture.setAuraTokenProvider(async () => "test-token");
  localStorage.setItem("aura_python_workspace_id", "test-workspace");
  window.open = () => { throw new Error("Meta consent must use the same tab"); };
});

after(() => {
  globalThis.fetch = originalFetch;
  dom?.window.close();
  for (const key of ["window", "document", "localStorage", "Element", "HTMLElement", "IS_REACT_ACT_ENVIRONMENT"]) delete globalThis[key];
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else delete globalThis.navigator;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});

async function renderConnections(initial, { failCheck = false } = {}) {
  window.history.replaceState(null, "", "/?connect=meta-ads");
  let saved = initial.map((tool) => ({ ...tool }));
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    const target = new URL(url), pathname = target.pathname;
    requests.push({ pathname, search: target.search, method: options.method });
    if (pathname === "/v1/managed-connectors/status") return Response.json({ marketplace: catalog });
    if (pathname === "/v1/connector-broker/apps") return Response.json({ apps: catalog });
    if (pathname === "/v1/tools") return Response.json(saved);
    if (pathname === "/v1/agents") return Response.json(saved.filter((tool) => tool.is_agent).map((tool) => ({ ...tool, name: tool.display_name, protocol: "mcp" })));
    if (pathname.endsWith("/session")) return Response.json({ detail: "Consent is temporarily unavailable" }, { status: 409 });
    if (pathname.endsWith("/test")) {
      if (failCheck) return Response.json({ detail: "Verification unavailable" }, { status: 503 });
      return Response.json({ status: "verified", verification: { ok: true } });
    }
    if (options.method === "DELETE") {
      saved = saved.filter((tool) => pathname !== `/v1/connections/${tool.id}`);
      return Response.json({ disconnected: true });
    }
    throw new Error(`Unexpected request: ${pathname}`);
  };
  const snapshot = await fixture.hydrateConnections({ force: true });
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(React.createElement(fixture.ConnectionsPill)));
  return { container, requests, snapshot,
    failVerification: () => { failCheck = true; },
    row: (key) => container.querySelector(`[data-connection-row="${key}"]`),
    click: async (element) => { assert.ok(element, "Expected an actionable button"); await act(async () => element.click()); },
    button: (text) => [...container.querySelectorAll("button")].find((button) => button.textContent === text),
    close: async () => { await act(async () => root.unmount()); container.remove(); },
  };
}

test("Pipeboard-only workspace offers direct Connect and targets that route even when consent fails", async () => {
  const ui = await renderConnections([pipeboard]);
  try {
    assert.match(ui.row("route:meta-ads-direct").textContent, /Meta Ads — Direct.*Connect/);
    assert.match(ui.row("connection:pipeboard").textContent, /Meta Ads — Pipeboard.*Connected.*Manage/);
    assert.equal(ui.container.textContent.includes("No agents connected yet."), true);
    await ui.click(ui.row("route:meta-ads-direct").querySelector("button"));
    const session = ui.requests.find((request) => request.pathname.endsWith("/session"));
    assert.equal(session.pathname, "/v1/connector-broker/meta-ads-direct/session");
    assert.equal(session.search, "");
    assert.equal(ui.row("route:meta-ads-direct").querySelector("button").textContent, "Connect");
    assert.match(ui.row("connection:pipeboard").textContent, /Connected/);
  } finally { await ui.close(); }
});

for (const selected of [direct, pipeboard]) {
  test(`Manage, Test, Reconnect and Remove use only the selected ${selected.id} connection`, async () => {
    const ui = await renderConnections([pipeboard, direct]);
    try {
      await ui.click(ui.row(`connection:${selected.id}`).querySelector("button"));
      assert.match(ui.container.textContent, /This connection has its own authorization/);
      ui.requests.length = 0;
      await ui.click(ui.button("Test"));
      assert.equal(ui.requests[1].pathname, `/v1/connections/${selected.id}/test`);
      await ui.click(ui.button("Reconnect"));
      const session = ui.requests.find((request) => request.pathname.endsWith("/session"));
      assert.equal(session.pathname, `/v1/connector-broker/${selected.slug}/session`);
      assert.equal(new URLSearchParams(session.search).get("connection_id"), selected.id);
      await ui.click(ui.button("Remove"));
      assert.deepEqual(ui.requests.filter((request) => request.method === "DELETE").map((request) => request.pathname), [`/v1/connections/${selected.id}`]);
      const other = selected.id === "direct" ? "pipeboard" : "direct";
      assert.match(ui.row(`connection:${other}`).textContent, /Connected.*Manage/);
      assert.equal(ui.row(`connection:${selected.id}`), null);
    } finally { await ui.close(); }
  });
}

test("failed live check overrides stale verified direct status without requesting reconnection", async () => {
  const ui = await renderConnections([pipeboard, direct], { failCheck: true });
  try {
    assert.equal(ui.snapshot.find((tool) => tool.id === "direct").verification.ok, false);
    assert.match(ui.row("connection:direct").textContent, /Check connection.*Manage/);
    await ui.click(ui.row("connection:direct").querySelector("button"));
    assert.match(ui.container.textContent, /Connection needs checking/);
    assert.ok(!ui.container.textContent.includes("Connected and verified"));
    assert.ok(ui.requests.every((request) => !request.pathname.endsWith("/session")));
    assert.match(ui.row("connection:pipeboard").textContent, /Connected/);
  } finally { await ui.close(); }
});

test("a failed Test action clears the selected connection's green status without affecting Pipeboard", async () => {
  const ui = await renderConnections([pipeboard, direct]);
  try {
    await ui.click(ui.row("connection:direct").querySelector("button"));
    assert.match(ui.container.textContent, /Connected and verified/);
    ui.failVerification();
    await ui.click(ui.button("Test"));
    assert.match(ui.container.textContent, /Connection needs checking/);
    assert.match(ui.row("connection:direct").textContent, /Check connection/);
    assert.match(ui.row("connection:pipeboard").textContent, /Connected/);
    assert.ok(ui.requests.every((request) => !request.pathname.endsWith("/session")));
  } finally { await ui.close(); }
});
