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
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent", base: "/aura-workflow-demo/",
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

function popupBrowser({ forbidDocument = false } = {}) {
  const namedWindows = new Map();
  const popups = [];
  const openedUrls = [];
  const destinations = [];
  const listeners = new Map();
  return {
    popups, openedUrls, destinations, listeners,
    location: { origin: "https://aura.example.invalid" },
    addEventListener(name, listener) { listeners.set(name, listener); },
    removeEventListener(name) { listeners.delete(name); },
    setTimeout(callback) { callback(); },
    open(url, target) {
      openedUrls.push(url);
      // Navigating an existing named window does not synchronously replace its
      // cross-origin document with about:blank.
      const existing = namedWindows.get(target);
      if (existing && !existing.closed) return existing;
      const document = { title: "", body: { innerHTML: "" } };
      let crossOrigin = false;
      const popup = {
        closed: false,
        get document() {
          if (crossOrigin || forbidDocument) throw new DOMException("Blocked access to a cross-origin document", "SecurityError");
          return document;
        },
        location: {
          get assign() {
            if (crossOrigin) throw new DOMException("Blocked access to cross-origin location.assign", "SecurityError");
            return (destination) => { crossOrigin = destination !== "about:blank"; destinations.push(destination); };
          },
          set href(destination) { crossOrigin = true; destinations.push(destination); },
        },
        close() { this.closed = true; },
      };
      if (target !== "_blank") namedWindows.set(target, popup);
      popups.push(popup);
      return popup;
    },
  };
}

test("connect and reconnect retries do not access an earlier provider window's document", () => {
  for (const reconnecting of [false, true]) {
    globalThis.window = popupBrowser();
    const earlier = flow.reserveAuthorizationWindow("google", reconnecting);
    earlier.location.assign("https://connect.example.invalid/google");
    assert.throws(() => earlier.document, { name: "SecurityError" });

    const retry = flow.reserveAuthorizationWindow("google", reconnecting);
    assert.notEqual(retry, earlier);
    const preparation = new URL(window.openedUrls.at(-1), window.location.origin);
    assert.equal(preparation.origin, window.location.origin);
    assert.ok(preparation.pathname.startsWith("/aura-workflow-demo/"));
    assert.equal(earlier.closed, false);
  }
});

test("preparing authorization never needs access to the popup's document", () => {
  globalThis.window = popupBrowser({ forbidDocument: true });
  for (const reconnecting of [false, true]) {
    const popup = flow.reserveAuthorizationWindow("google", reconnecting);
    assert.equal(popup.closed, false);
    assert.throws(() => popup.document, { name: "SecurityError" });
  }
});

test("a blocked authorization popup still gives actionable guidance", () => {
  globalThis.window = { open: () => null };
  assert.throws(() => flow.reserveAuthorizationWindow("google"), /Allow pop-ups for AURA/);
});

test("a managed retry verifies Google access without reading the cross-origin popup", async () => {
  const { saved } = setup();
  globalThis.window = popupBrowser();
  const earlier = flow.reserveAuthorizationWindow("google");
  earlier.location.assign("https://connect.example.invalid/previous");
  const retry = flow.reserveAuthorizationWindow("google");
  retry.location.href = "https://connect.example.invalid/previous";
  const requests = [];
  const google = { id: "google-connection", slug: "google", enabled: true };
  globalThis.fetch = async (url, options) => {
    const { pathname } = new URL(url);
    requests.push(pathname);
    assert.equal(options.headers["X-Workspace-Id"], "test-workspace");
    assert.equal(options.headers.Authorization, "Bearer test-user-token");
    if (pathname === "/v1/managed-connectors/google/sync") {
      return Response.json({ connected: true, tool_id: google.id });
    }
    if (pathname === `/v1/connections/${google.id}/test`) {
      return Response.json({ status: "verified", verification: { ok: true } });
    }
    if (pathname === "/v1/tools") return Response.json([google]);
    throw new Error(`Unexpected request: ${pathname}`);
  };

  const result = await flow.authorizeManagedConnector("google", 1000, retry, {
    connect_link: "https://connect.example.invalid/current",
  });
  assert.equal(result.connected, true);
  assert.equal(result.tool.id, google.id);
  assert.deepEqual(requests, ["/v1/managed-connectors/google/sync", `/v1/connections/${google.id}/test`, "/v1/tools"]);
  assert.equal(retry.closed, true);
  assert.equal(earlier.closed, false);
  assert.equal(saved.get("aura_active_python_run_id"), "saved-run");
});

test("native authorization navigates a cross-origin popup and waits for the provider callback", async () => {
  setup();
  globalThis.window = popupBrowser();
  const popup = window.open("about:blank", "_blank");
  popup.location.href = "https://accounts.example.invalid/previous";
  let callbackSent = false;
  window.setTimeout = (callback) => {
    window.listeners.get("message")({ origin: window.location.origin,
      data: { source: "aura-oauth", provider: "google", status: "success" } });
    callbackSent = true;
    callback();
  };
  const google = { id: "google-native", slug: "google", enabled: true, updated_at: "new" };
  globalThis.fetch = async (url) => {
    assert.equal(new URL(url).pathname, "/v1/tools");
    return Response.json(callbackSent ? [google] : []);
  };
  const authorization_url = "https://accounts.example.invalid/current";
  const result = await flow.authorizeOAuth("google", 1000, popup, { authorization_url });
  assert.equal(result.connected, true);
  assert.equal(callbackSent, true);
  assert.equal(window.destinations.at(-1), authorization_url);
  assert.equal(popup.closed, true);
  assert.equal(window.listeners.size, 0);
});

test("the connection reconnect endpoint can navigate a cross-origin popup", async () => {
  setup();
  globalThis.window = popupBrowser();
  const popup = window.open("about:blank", "_blank");
  popup.location.href = "https://accounts.example.invalid/previous";
  const google = { id: "google-native", slug: "google", enabled: true, updated_at: "old" };
  const authorization_url = "https://accounts.example.invalid/current";
  globalThis.fetch = async (url) => {
    const { pathname } = new URL(url);
    if (pathname === `/v1/connections/${google.id}/reconnect`) {
      return Response.json({ authorization_url, previous_updated_at: "old" });
    }
    if (pathname === "/v1/tools") return Response.json([{ ...google, updated_at: "new" }]);
    throw new Error(`Unexpected request: ${pathname}`);
  };
  const result = await flow.reconnectPythonConnection(google, 1000, popup);
  assert.equal(result.connected, true);
  assert.equal(window.destinations.at(-1), authorization_url);
  assert.equal(popup.closed, true);
});
