import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const repo = fileURLToPath(new URL("../", import.meta.url));
let temporary, flow;
const originalFetch = globalThis.fetch;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".connection-flow-"));
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    define: { "import.meta.env.VITE_AURA_API_URL": JSON.stringify("https://api.example.invalid") },
    build: { ssr: path.join(repo, "tests/fixtures/connectionFlow.mjs"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "flow.mjs" } } },
  });
  flow = await import(pathToFileURL(path.join(temporary, "flow.mjs")));
  flow.mergeMarketplaceApps([{
    name: "Meta Ads", display_name: "Meta Ads", provider: "meta-ads-mcp",
    canonical_provider: "meta-ads", connectable: true, connection_backend: "managed_mcp",
    availability: "available", connection_strategy: "oauth",
  }]);
  flow.setAuraTokenProvider(async () => "test-user-token");
});
after(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
  delete globalThis.localStorage;
  if (temporary) fs.rmSync(temporary, { recursive: true, force: true });
});

const account = { id: "test-connection", slug: "agent-meta-ads-0123456789",
  display_name: "Meta Ads", canonical_provider: "meta-ads", connection_backend: "managed_mcp" };

function setup({ existing = false, failure = false } = {}) {
  const requests = [], navigations = [];
  const saved = new Map([["aura_python_workspace_id", "test-workspace"], ["aura_active_python_run_id", "saved-run"]]);
  globalThis.localStorage = { getItem: (key) => saved.get(key), setItem: (key, value) => saved.set(key, value) };
  globalThis.window = {
    open() { throw new Error("Safari blocked the popup"); },
    sessionStorage: { setItem() {} }, location: { assign: (url) => navigations.push(url) },
  };
  globalThis.fetch = async (url, options) => {
    const target = new URL(url);
    requests.push({ path: target.pathname, search: target.search, options });
    assert.equal(options.headers["X-Workspace-Id"], "test-workspace");
    assert.equal(options.headers.Authorization, "Bearer test-user-token");
    if (target.pathname === "/v1/tools") return Response.json(existing ? [account] : []);
    if (target.pathname.startsWith("/v1/connector-broker/") && target.pathname.endsWith("/session")) {
      if (failure) return Response.json({ detail: "Consent is unavailable" }, { status: 409 });
      return Response.json({ backend: "native", provider: account.slug, connection_id: account.id,
        authorization_url: "https://pipeboard.co/oauth/authorize?platform=meta-ads&state=server-generated" });
    }
    throw new Error(`Unexpected request: ${target.pathname}`);
  };
  return { requests, navigations, saved };
}

test("new Meta Ads consent uses the authenticated broker and navigates without opening a popup", async () => {
  const context = setup();
  const result = await flow.connectTool("Meta Ads");
  assert.equal(result.connected, false);
  assert.equal(result.authorizationStarted, true);
  assert.equal(context.navigations.length, 1);
  assert.equal(context.requests[1].path, "/v1/connector-broker/meta-ads-mcp/session");
  assert.equal(context.requests[1].options.method, "POST");
  assert.equal(flow.getAllConnections()["Meta Ads"], undefined);
  assert.equal(context.saved.get("aura_active_python_run_id"), "saved-run");
  assert.equal(context.saved.get("aura_python_workspace_id"), "test-workspace");
});

test("an existing pending Meta account also skips popup reservation", async () => {
  const context = setup({ existing: true });
  const result = await flow.connectTool("Meta Ads");
  assert.equal(result.authorizationStarted, true);
  assert.equal(result.connected, false);
  assert.equal(context.requests[1].path, `/v1/connector-broker/${account.slug}/session`);
  assert.equal(new URLSearchParams(context.requests[1].search).get("connection_id"), account.id);
  assert.equal(context.navigations.length, 1);
});

test("Meta reconnect returns a pending redirect without testing or refreshing access prematurely", async () => {
  const context = setup({ existing: true });
  const result = await flow.reconnectTool("Meta Ads", account.id);
  assert.deepEqual(result, { redirecting: true, connected: false });
  assert.equal(context.requests.length, 2);
  assert.equal(context.navigations.length, 1);
});

test("broker failure leaves the account unconnected and the saved run in place", async () => {
  const context = setup({ failure: true });
  await assert.rejects(flow.connectTool("Meta Ads"), /Consent is unavailable/);
  assert.equal(context.navigations.length, 0);
  assert.equal(flow.getAllConnections()["Meta Ads"], undefined);
  assert.equal(context.saved.get("aura_active_python_run_id"), "saved-run");
});

// Model the browser's WindowProxy restrictions, including a named popup that
// remains on a provider origin when the user retries the same connection.
function popupBrowser() {
  const named = new Map(), popups = [], navigations = [], listeners = new Set();
  function popup() {
    let foreign = false;
    const document = { title: "", body: { innerHTML: "" } };
    const location = {
      set href(url) { navigations.push(url); foreign = true; },
      get assign() {
        if (foreign) throw new DOMException("Blocked cross-origin Location.assign", "SecurityError");
        return (url) => { location.href = url; };
      },
    };
    return {
      closed: false, location,
      get document() {
        if (foreign) throw new DOMException("Blocked cross-origin Window.document", "SecurityError");
        return document;
      },
      close() { this.closed = true; },
    };
  }
  globalThis.window = {
    location: { origin: "https://aura.example" },
    open(url, target) {
      if (target !== "_blank" && named.has(target)) return named.get(target);
      const next = popup();
      popups.push(next);
      if (target !== "_blank") named.set(target, next);
      return next;
    },
    setTimeout(callback) {
      return setTimeout(() => {
        for (const listener of listeners) listener({
          origin: "https://aura.example",
          data: { source: "aura-oauth", provider: "google", status: "success" },
        });
        callback();
      }, 0);
    },
    addEventListener(type, listener) { if (type === "message") listeners.add(listener); },
    removeEventListener(type, listener) { if (type === "message") listeners.delete(listener); },
  };
  return { popups, navigations, listeners };
}

test("retrying Google connect or reconnect leaves the previous cross-origin popup untouched", () => {
  for (const reconnecting of [false, true]) {
    const browser = popupBrowser();
    const previous = flow.reserveAuthorizationWindow("google", reconnecting);
    previous.location.href = "https://accounts.google.com/";
    const retry = flow.reserveAuthorizationWindow("google", reconnecting);
    assert.notEqual(retry, previous);
    assert.equal(previous.closed, false);
    assert.match(retry.document.title, /AURA/);
    assert.equal(browser.popups.length, 2);
  }
});

test("an inaccessible loading document does not abort popup reservation", () => {
  const browser = popupBrowser();
  const providerWindow = window.open("about:blank", "_blank");
  providerWindow.location.href = "https://accounts.google.com/";
  window.open = () => providerWindow;
  assert.equal(flow.reserveAuthorizationWindow("google"), providerWindow);
  assert.deepEqual(browser.navigations, ["https://accounts.google.com/"]);
});

test("a blocked popup still gives actionable browser guidance", () => {
  popupBrowser();
  window.open = () => null;
  assert.throws(() => flow.reserveAuthorizationWindow("google"), /Allow pop-ups for AURA/);
});

function googleAuthorization({ verified = true } = {}) {
  const browser = popupBrowser();
  const requests = [];
  const tool = { id: "google-connection", slug: "google", kind: "oauth", enabled: true, updated_at: "new" };
  const saved = new Map([["aura_python_workspace_id", "test-workspace"]]);
  globalThis.localStorage = { getItem: (key) => saved.get(key), setItem: (key, value) => saved.set(key, value) };
  globalThis.fetch = async (url, options) => {
    const target = new URL(url);
    requests.push(target.pathname);
    assert.equal(options.headers.Authorization, "Bearer test-user-token");
    assert.equal(options.headers["X-Workspace-Id"], "test-workspace");
    if (target.pathname === "/v1/tools") return Response.json([tool]);
    if (target.pathname === "/v1/managed-connectors/google/sync") {
      return Response.json({ connected: true, tool_id: tool.id });
    }
    if (target.pathname === `/v1/connections/${tool.id}/test`) {
      return Response.json({ status: verified ? "verified" : "unverified", verification: { ok: verified } });
    }
    if (target.pathname === `/v1/connections/${tool.id}/reconnect`) {
      return Response.json({ authorization_url: "https://accounts.google.com/consent", previous_updated_at: "old" });
    }
    throw new Error(`Unexpected request: ${target.pathname}`);
  };
  const reserved = flow.reserveAuthorizationWindow("google");
  // The window can change origin while the authenticated session request waits.
  reserved.location.href = "https://accounts.google.com/previous-attempt";
  browser.navigations.length = 0;
  return { ...browser, requests, tool, reserved };
}

test("managed Google consent navigates a cross-origin popup and requires backend verification", async () => {
  const context = googleAuthorization();
  const result = await flow.authorizeManagedConnector("google", 1000, context.reserved, {
    connect_link: "https://connect.nango.dev/google", tool_connection_id: context.tool.id,
  });
  assert.equal(result.connected, true);
  assert.equal(result.tool.id, context.tool.id);
  assert.deepEqual(context.navigations, ["https://connect.nango.dev/google"]);
  assert.deepEqual(context.requests, ["/v1/managed-connectors/google/sync", `/v1/connections/${context.tool.id}/test`, "/v1/tools"]);
  assert.equal(context.reserved.closed, true);
});

test("managed consent cannot report success when the connection test fails", async () => {
  const context = googleAuthorization({ verified: false });
  await assert.rejects(flow.authorizeManagedConnector("google", 10, context.reserved, {
    connect_link: "https://connect.nango.dev/google", tool_connection_id: context.tool.id,
  }), /did not finish connecting/);
  assert.equal(context.reserved.closed, true);
  assert.equal(context.requests.includes("/v1/tools"), false);
});

test("native Google consent navigates a cross-origin popup and still waits for its callback", async () => {
  const context = googleAuthorization();
  const result = await flow.authorizeOAuth("google", 1000, context.reserved, {
    authorization_url: "https://accounts.google.com/consent", previous_updated_at: "old",
  });
  assert.equal(result.connected, true);
  assert.deepEqual(context.navigations, ["https://accounts.google.com/consent"]);
  assert.equal(context.reserved.closed, true);
  assert.equal(context.listeners.size, 0);
});

test("legacy reconnect also navigates a cross-origin reserved popup", async () => {
  const context = googleAuthorization();
  const result = await flow.reconnectPythonConnection(context.tool, 1000, context.reserved);
  assert.equal(result.connected, true);
  assert.deepEqual(context.navigations, ["https://accounts.google.com/consent"]);
  assert.equal(context.reserved.closed, true);
});
