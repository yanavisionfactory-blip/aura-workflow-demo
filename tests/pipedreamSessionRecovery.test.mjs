import assert from "node:assert/strict";
import { before, after, test } from "node:test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const repo = fileURLToPath(new URL("../", import.meta.url));
const originals = Object.fromEntries(["fetch", "window", "document", "localStorage"].map((key) => [key, globalThis[key]]));
let temporary, flow;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".pipedream-session-"));
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    define: { "import.meta.env.VITE_AURA_API_URL": JSON.stringify("https://api.example.invalid") },
    build: { ssr: path.join(repo, "tests/fixtures/connectionFlow.mjs"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "flow.mjs" } } },
  });
  flow = await import(pathToFileURL(path.join(temporary, "flow.mjs")));
  flow.setAuraTokenProvider(async () => "test-user-token");
});
after(() => {
  for (const [key, value] of Object.entries(originals)) {
    if (value === undefined) delete globalThis[key];
    else globalThis[key] = value;
  }
  fs.rmSync(temporary, { recursive: true, force: true });
});

const expired = "This session has expired. Please refresh the page to try again.";
const tool = { id: "sheets-connection", slug: "google-sheets", enabled: true };
function grant(number, extra = {}) {
  return { backend: "pipedream", provider: "google-sheets", app: "google_sheets",
    token: `grant-${number}`, expires_at: new Date(Date.now() + 900000).toISOString(),
    external_user_id: "opaque-test-user", project_environment: "production",
    account_id: "apn_existing", connection_id: tool.id, authorization_state: `state-${number}`, ...extra };
}

function fixture({ sessions = [grant(1), grant(2)], messages = [{ type: "error", message: expired }, { type: "success", authProvisionId: "apn_verified" }], completionStatus = 200 } = {}) {
  const frames = [], opened = [], listeners = new Set(), requests = [], completions = [];
  const saved = new Map([["aura_python_workspace_id", "workspace"], ["aura_active_python_run_id", "saved-run"]]);
  globalThis.localStorage = { getItem: (key) => saved.get(key), setItem: (key, value) => saved.set(key, value) };
  globalThis.window = {
    setTimeout, clearTimeout,
    addEventListener: (type, listener) => listeners.add(listener),
    removeEventListener: (type, listener) => listeners.delete(listener),
  };
  globalThis.document = {
    createElement: () => ({ style: {}, contentWindow: {}, remove() {
      const index = frames.indexOf(this);
      if (index !== -1) frames.splice(index, 1);
      this.contentWindow = null;
    } }),
    querySelectorAll: () => [...frames],
    body: { appendChild(frame) {
      const index = opened.length;
      opened.push(new URL(frame.src));
      frames.push(frame);
      frame.onload?.();
      const source = frame.contentWindow;
      setImmediate(() => {
        const message = messages[index];
        if (!message) return;
        for (const listener of [...listeners]) listener({ origin: "https://pipedream.com", source, data: message });
      });
    } },
  };
  let sessionCount = 0;
  globalThis.fetch = async (url, options) => {
    const target = new URL(url);
    requests.push(target);
    assert.equal(options.headers.Authorization, "Bearer test-user-token");
    assert.equal(options.headers["X-Workspace-Id"], "workspace");
    if (target.pathname.endsWith("/session")) {
      const session = sessions[sessionCount++];
      assert.ok(session, "must not retry indefinitely");
      return typeof session === "function" ? session() : Response.json(session);
    }
    if (target.pathname.endsWith("/complete")) {
      completions.push(JSON.parse(options.body));
      return Response.json(completionStatus === 200 ? { connection_id: tool.id } : { detail: expired }, { status: completionStatus });
    }
    if (target.pathname === "/v1/tools") return Response.json([tool]);
    throw new Error(`Unexpected request: ${target.pathname}`);
  };
  return { frames, opened, listeners, requests, completions, saved,
    connect: (timeoutMs = 1000) => flow.authorizeConnectorBroker("google-sheets", { connection: tool, timeoutMs }) };
}

test("expired Sheets consent opens a fresh session and completes with its matching state", async () => {
  const context = fixture();
  const result = await context.connect();
  assert.equal(result.connected, true);
  assert.equal(result.tool.id, tool.id);
  assert.deepEqual(context.opened.map((url) => Object.fromEntries(url.searchParams)), [
    { token: "grant-1", app: "google_sheets", accountId: "apn_existing" },
    { token: "grant-2", app: "google_sheets", accountId: "apn_existing" },
  ]);
  assert.deepEqual(context.completions, [{ account_id: "apn_verified", connection_id: tool.id, authorization_state: "state-2" }]);
  assert.equal(context.requests.filter((url) => url.pathname.endsWith("/session")).length, 2);
  assert.ok(context.requests.filter((url) => url.pathname.endsWith("/session")).every((url) => url.searchParams.get("connection_id") === tool.id));
  assert.equal(context.frames.length, 0);
  assert.equal(context.listeners.size, 0);
  assert.equal(context.saved.get("aura_active_python_run_id"), "saved-run");
});

test("an already expired grant is renewed before the consent iframe opens", async () => {
  const context = fixture({ sessions: [grant(1, { expires_at: new Date(Date.now() - 1000).toISOString() }), grant(2)],
    messages: [{ type: "success", authProvisionId: "apn_verified" }] });
  await context.connect();
  assert.deepEqual(context.opened.map((url) => url.searchParams.get("token")), ["grant-2"]);
  assert.equal(context.completions[0].authorization_state, "state-2");
});

test("repeated expiry stops after one renewal and keeps the saved work", async () => {
  const context = fixture({ messages: [{ type: "error", message: expired }, { type: "error", message: expired }] });
  await assert.rejects(context.connect(), /expired again.*Click Connect/);
  assert.equal(context.requests.length, 2);
  assert.equal(context.completions.length, 0);
  assert.equal(context.frames.length, 0);
  assert.equal(context.listeners.size, 0);
  assert.equal(context.saved.get("aura_python_workspace_id"), "workspace");
  assert.equal(context.saved.get("aura_active_python_run_id"), "saved-run");
});

test("denied consent and user cancellation do not renew or save a connection", async () => {
  for (const message of [{ type: "error", message: "Access denied" }, { type: "close" }]) {
    const context = fixture({ messages: [message] });
    await assert.rejects(context.connect(), /Access denied|cancelled/);
    assert.equal(context.requests.length, 1);
    assert.equal(context.completions.length, 0);
    assert.equal(context.frames.length, 0);
    assert.equal(context.listeners.size, 0);
  }
});

test("renewed consent cannot switch the app, tenant, environment or selected account", async () => {
  for (const extra of [
    { provider: "google-ads", app: "google_ads" }, { app: "facebook_ads" },
    { backend: "native" }, { external_user_id: "another-user" },
    { project_environment: "development" }, { connection_id: "another-connection" },
    { account_id: "apn_another" }, { token: null, already_connected: true },
  ]) {
    const context = fixture({ sessions: [grant(1), grant(2, extra)] });
    await assert.rejects(context.connect(), /different app|could not renew/);
    assert.equal(context.opened.length, 1);
    assert.equal(context.completions.length, 0);
    assert.equal(context.frames.length, 0);
    assert.equal(context.listeners.size, 0);
  }
});

test("an expired backend completion is not replayed as another consent attempt", async () => {
  const context = fixture({ messages: [{ type: "success", authProvisionId: "apn_verified" }], completionStatus: 409 });
  await assert.rejects(context.connect(), /session has expired/);
  assert.equal(context.opened.length, 1);
  assert.equal(context.requests.filter((url) => url.pathname.endsWith("/session")).length, 1);
  assert.equal(context.completions.length, 1);
});

test("renewal failure surfaces the broker error without completing or looping", async () => {
  const context = fixture({ sessions: [grant(1), () => Response.json({ detail: "Consent is unavailable" }, { status: 503 })] });
  await assert.rejects(context.connect(), /Consent is unavailable/);
  assert.equal(context.opened.length, 1);
  assert.equal(context.requests.length, 2);
  assert.equal(context.completions.length, 0);
});

test("a late session response cannot reopen consent after the connection deadline", async () => {
  let finishRefresh;
  const context = fixture({ sessions: [grant(1), () => new Promise((resolve) => { finishRefresh = resolve; })] });
  await assert.rejects(context.connect(50), /did not finish connecting/);
  assert.equal(typeof finishRefresh, "function");
  finishRefresh(Response.json(grant(2)));
  await new Promise(setImmediate);
  assert.equal(context.opened.length, 1);
  assert.equal(context.frames.length, 0);
  assert.equal(context.listeners.size, 0);
  assert.equal(context.completions.length, 0);
});

test("new accounts renew with no existing connection or provider account id", async () => {
  const context = fixture({ sessions: [grant(1, { connection_id: null, account_id: null }), grant(2, { connection_id: null, account_id: null })] });
  await flow.authorizeConnectorBroker("google-sheets", { timeoutMs: 1000 });
  assert.ok(context.requests.filter((url) => url.pathname.endsWith("/session")).every((url) => !url.searchParams.has("connection_id")));
  assert.ok(context.opened.every((url) => !url.searchParams.has("accountId")));
  assert.equal(context.completions[0].connection_id, null);
  assert.equal(context.completions[0].authorization_state, "state-2");
});
