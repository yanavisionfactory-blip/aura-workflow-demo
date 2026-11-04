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

test("a forced refresh after consent waits for fresh permissions instead of returning an older in-flight snapshot", async () => {
  setup();
  let finishOldVerification, markOldVerificationStarted;
  const oldVerification = new Promise((resolve) => { finishOldVerification = resolve; });
  const oldVerificationStarted = new Promise((resolve) => { markOldVerificationStarted = resolve; });
  let reads = 0;
  let granted = ["sheets.read"];
  globalThis.fetch = async (url) => {
    const target = new URL(url);
    if (target.pathname === "/v1/managed-connectors/status") return Response.json({});
    if (target.pathname === "/v1/tools") {
      reads += 1;
      return Response.json([{ id: "google-account", slug: "google", kind: "oauth",
        enabled: true, display_name: "Google Workspace", allowed_operations: granted }]);
    }
    if (target.pathname === "/v1/connections/google-account/test") {
      if (reads === 1) {
        markOldVerificationStarted();
        await oldVerification;
      }
      return Response.json({ status: "verified", verification: { ok: true } });
    }
    throw new Error(`Unexpected request: ${target.pathname}`);
  };

  const background = flow.hydrateConnections({ force: true });
  await oldVerificationStarted;
  granted = ["sheets.read", "sheets.append"];
  const afterConsent = flow.hydrateConnections({ force: true });
  const concurrentRefresh = flow.hydrateConnections({ force: true });
  finishOldVerification();
  const [oldTools, updatedTools, concurrentTools] = await Promise.all([background, afterConsent, concurrentRefresh]);
  assert.deepEqual(oldTools[0].allowed_operations, ["sheets.read"]);
  assert.deepEqual(updatedTools[0].allowed_operations, ["sheets.read", "sheets.append"]);
  assert.deepEqual(concurrentTools, updatedTools);
  assert.equal(reads, 2);
});

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
        focusCount: 0,
        focus() { this.focusCount += 1; },
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

function googleConnectionSelection(tools, { name = "Google Sheets", provider = "google-sheets" } = {}) {
  setup();
  globalThis.window = popupBrowser();
  flow.mergeMarketplaceApps([{
    display_name: name, provider, connectable: true,
    connection_backend: "pipedream", preferred_connection: true, connection_strategy: "oauth",
  }]);
  const requests = [];
  globalThis.fetch = async (url) => {
    const target = new URL(url);
    if (target.pathname === "/v1/tools") return Response.json(tools);
    if (target.pathname.startsWith("/v1/connector-broker/")) {
      requests.push(target);
      // Stop at the OAuth boundary: this test checks the route sent to the
      // real broker, without opening the provider's SDK or granting consent.
      return Response.json({ detail: "Stop before consent" }, { status: 409 });
    }
    throw new Error(`Unexpected request: ${target.pathname}`);
  };
  return requests;
}

test("Update Sheets access reserves native consent before asynchronous account discovery", async () => {
  const requests = googleConnectionSelection([{
    id: "workspace", slug: "google", display_name: "Google Workspace",
    connection_backend: "native", allowed_operations: ["sheets.read_range"],
  }]);
  const update = flow.connectTool("Google Sheets", { provider: "google" });
  assert.equal(window.popups.length, 1, "consent window opens in the original click gesture");
  assert.equal(requests.length, 0, "account discovery has not completed yet");
  await assert.rejects(update, /Stop before consent/);
  assert.equal(requests[0].pathname, "/v1/connector-broker/google/session");
  assert.equal(requests[0].searchParams.get("connection_id"), "workspace");
  assert.equal(window.popups[0].closed, true, "failed consent cleans up its preparation window");
});

for (const app of [
  { name: "Google Sheets", provider: "google-sheets", operation: "sheets.read_range" },
  { name: "Google Docs", provider: "google-docs", operation: "docs.create" },
]) {
  test(`new customer ${app.name} Connect starts on the managed route with no existing accounts`, async () => {
    const requests = googleConnectionSelection([], app);
    await assert.rejects(flow.connectTool(app.name), /Stop before consent/);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].pathname, `/v1/connector-broker/${app.provider}/session`);
    assert.equal(requests[0].searchParams.has("connection_id"), false);
    assert.equal(window.popups.length, 0);
  });

  test(`fresh ${app.name} Connect does not inherit a broad Workspace account`, async () => {
    for (const enabled of [false, true]) {
      const requests = googleConnectionSelection([{
        id: "legacy-workspace", slug: "google", display_name: "Google Workspace",
        connection_backend: "native", enabled, allowed_operations: [app.operation],
      }], app);
      await assert.rejects(flow.connectTool(app.name), /Stop before consent/);
      assert.equal(requests[0].pathname, `/v1/connector-broker/${app.provider}/session`);
      assert.equal(requests[0].searchParams.has("connection_id"), false);
      assert.equal(window.popups.length, 0);
    }
  });

  test(`${app.name} reconnects keep an explicitly selected Workspace account`, async () => {
    for (const connect of [flow.connectTool, (name, opts) => flow.reconnectTool(name, opts.connectionId)]) {
      const requests = googleConnectionSelection([{
        id: "legacy-workspace", slug: "google", display_name: "Google Workspace",
        connection_backend: "native", enabled: false, allowed_operations: [app.operation],
      }], app);
      await assert.rejects(connect(app.name, { connectionId: "legacy-workspace" }), /Stop before consent/);
      assert.equal(requests[0].pathname, "/v1/connector-broker/google/session");
      assert.equal(requests[0].searchParams.get("connection_id"), "legacy-workspace");
    }
  });

  test(`fresh ${app.name} Connect retains an existing account on its exact route`, async () => {
    for (const backend of ["native", "nango", "pipedream"]) {
      const requests = googleConnectionSelection([{
        id: "existing-google-app", slug: app.provider, display_name: app.name,
        connection_backend: backend, enabled: false,
      }], app);
      await assert.rejects(flow.connectTool(app.name), /Stop before consent/);
      assert.equal(requests[0].pathname, `/v1/connector-broker/${app.provider}/session`);
      assert.equal(requests[0].searchParams.get("connection_id"), "existing-google-app");
    }
  });
}

test("the selected Sheets route survives conflicting marketplace aliases and stale Meta state", async () => {
  const requests = googleConnectionSelection([]);
  flow.mergeMarketplaceApps([{
    provider: "unrelated-ads", display_name: "A shared ads connector", connectable: true,
    aliases: ["Google Sheets"], connection_backend: "managed_mcp",
  }]);
  const state = new Map([["aura_same_tab_authorization", JSON.stringify({ provider: account.slug, startedAt: Date.now() })]]);
  window.sessionStorage = { removeItem: (key) => state.delete(key) };
  await assert.rejects(flow.connectTool("Google Sheets", { provider: "google-sheets" }), /Stop before consent/);
  assert.equal(requests[0].pathname, "/v1/connector-broker/google-sheets/session");
  assert.equal(state.size, 0);
  assert.equal(window.popups.length, 0);
});

test("Google broker sessions reject another provider before consent or account reuse", async () => {
  for (const session of [
    { backend: "native", provider: account.slug, authorization_url: "https://pipeboard.co/oauth/authorize" },
    { backend: "pipedream", provider: "google-sheets", app: "facebook_ads" },
    { backend: "pipedream", provider: "google-sheets", app: "google_ads", already_connected: true, connection_id: "wrong-account" },
  ]) {
    setup();
    globalThis.fetch = async () => Response.json(session);
    await assert.rejects(flow.authorizeConnectorBroker("google-sheets"), /different app/);
  }
});

test("Google Ads starts with managed Google sign-in and no customer-number input", async () => {
  const requests = googleConnectionSelection([], { name: "Google Ads", provider: "google-ads" });
  await assert.rejects(flow.connectTool("Google Ads", { provider: "google-ads" }), /Stop before consent/);
  assert.equal(requests[0].pathname, "/v1/connector-broker/google-ads/session");
  assert.equal(requests[0].search, "");
  assert.equal(window.popups.length, 0);
});

test("matching Google broker identities remain valid for managed and legacy accounts", async () => {
  for (const provider of ["google-sheets", "google-docs", "google-ads", "google-analytics"]) {
    for (const backend of ["native", "nango", "pipedream"]) {
      setup();
      const session = { backend, provider, app: provider.replaceAll("-", "_") };
      globalThis.fetch = async () => Response.json(session);
      assert.deepEqual(await flow.createConnectorBrokerSession(provider), session);
    }
  }
});

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

test("cancelling managed consent releases a hung sync and ignores its late success", async () => {
  const { saved } = setup();
  globalThis.window = popupBrowser();
  const controller = new AbortController();
  const progress = [], requests = [];
  let finishSync, syncSignal, markStarted;
  const started = new Promise((resolve) => { markStarted = resolve; });
  globalThis.fetch = (url, options) => {
    requests.push(new URL(url).pathname);
    syncSignal = options.signal;
    markStarted();
    // Deliberately ignore abort, like a response already queued by the browser.
    return new Promise((resolve) => { finishSync = resolve; });
  };
  const pending = flow.authorizeManagedConnector("google", 1000, null,
    { connect_link: "https://connect.example.invalid/google", tool_connection_id: "google-account" },
    { signal: controller.signal, onProgress: (value) => progress.push(value) });
  await started;
  assert.equal(progress.at(-1).phase, "waiting");
  progress.at(-1).focus();
  assert.equal(window.popups[0].focusCount, 1);
  controller.abort(new Error("Connection cancelled. Your plan is unchanged."));
  await assert.rejects(pending, /Connection cancelled/);
  assert.equal(window.popups[0].closed, true);
  assert.equal(syncSignal.aborted, true);
  finishSync(Response.json({ connected: true, tool_id: "google-account" }));
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(requests, ["/v1/managed-connectors/google/sync"]);
  assert.equal(progress.length, 1, "no verification or success after cancellation");
  assert.equal(saved.get("aura_active_python_run_id"), "saved-run");
});

test("the managed consent deadline closes the popup even when sync never returns", async () => {
  setup();
  globalThis.window = popupBrowser();
  let syncSignal;
  globalThis.fetch = (_url, options) => { syncSignal = options.signal; return new Promise(() => {}); };
  await assert.rejects(flow.authorizeManagedConnector("google", 30, null,
    { connect_link: "https://connect.example.invalid/google" }), /Sign-in timed out/);
  assert.equal(syncSignal.aborted, true);
  assert.equal(window.popups[0].closed, true);
});

test("managed consent stops after repeated service failures instead of hiding them for ten minutes", async () => {
  setup();
  globalThis.window = popupBrowser();
  const progress = [];
  let attempts = 0;
  globalThis.fetch = async () => {
    attempts += 1;
    return Response.json({ detail: "Connection check is unavailable" }, { status: 503 });
  };
  await assert.rejects(flow.authorizeManagedConnector("google", 1000, null,
    { connect_link: "https://connect.example.invalid/google" },
    { onProgress: (value) => progress.push(value.phase) }), /Connection check is unavailable/);
  assert.equal(attempts, 3);
  assert.deepEqual(progress, ["waiting", "retrying", "retrying"]);
  assert.equal(window.popups[0].closed, true);
});

test("cancelling native consent removes its callback listener while a read is stalled", async () => {
  setup();
  globalThis.window = popupBrowser();
  const controller = new AbortController();
  globalThis.fetch = () => new Promise(() => {});
  const pending = flow.authorizeOAuth("google", 1000, null,
    { authorization_url: "https://accounts.example.invalid/google" }, { signal: controller.signal });
  assert.equal(window.listeners.has("message"), true);
  controller.abort(new Error("Connection cancelled"));
  await assert.rejects(pending, /Connection cancelled/);
  assert.equal(window.listeners.size, 0);
  assert.equal(window.popups[0].closed, true);
});

test("Connect can time out during account discovery and closes its synchronously reserved window", async () => {
  googleConnectionSelection([]);
  globalThis.fetch = () => new Promise(() => {});
  const pending = flow.connectTool("Google Sheets", { provider: "google", timeoutMs: 30 });
  assert.equal(window.popups.length, 1);
  await assert.rejects(pending, /Sign-in timed out/);
  assert.equal(window.popups[0].closed, true);
});

test("a request deadline still applies with an external abort signal and aborts the fetch", async () => {
  setup();
  const controller = new AbortController();
  let requestSignal;
  globalThis.fetch = (_url, options) => { requestSignal = options.signal; return new Promise(() => {}); };
  await assert.rejects(flow.auraRequest("/v1/tools", { signal: controller.signal, timeoutMs: 30 }), /took too long/);
  assert.equal(requestSignal.aborted, true);
  assert.equal(controller.signal.aborted, false);
});

test("request deadlines include a stalled token lookup and prevent a late network request", async () => {
  setup();
  let finishToken, requests = 0;
  flow.setAuraTokenProvider(() => new Promise((resolve) => { finishToken = resolve; }));
  globalThis.fetch = async () => { requests += 1; return Response.json([]); };
  try {
    await assert.rejects(flow.auraRequest("/v1/tools", { timeoutMs: 30 }), /took too long/);
    finishToken("late-token");
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(requests, 0);
  } finally { flow.setAuraTokenProvider(async () => "test-user-token"); }
});
