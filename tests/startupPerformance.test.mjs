import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("signed-in users see the demo while workspace hydration continues", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const auth = readFileSync(new URL("../src/lib/AuthContext.jsx", import.meta.url), "utf8");
  const api = readFileSync(new URL("../src/lib/auraApi.js", import.meta.url), "utf8");
  assert.equal(app.includes('element={<Demo />}'), true);
  assert.equal(app.includes("Opening your workspace"), false);
  assert.equal(app.includes("Preparing your workspace"), false);
  assert.equal(app.includes("The demo remains available"), true);
  assert.equal(auth.match(/useLayoutEffect\(\(\) =>/g)?.length, 2);
  assert.equal(api.includes("if (!workspaceBootstrapPromise)"), true);
});

test("startup connection hydration is single-flight and not duplicated by Demo", () => {
  const service = readFileSync(new URL("../src/lib/connectService.js", import.meta.url), "utf8");
  const demo = readFileSync(new URL("../src/pages/Demo.jsx", import.meta.url), "utf8");
  assert.equal(service.includes("if (hydrationPromise) return hydrationPromise"), true);
  assert.equal(service.includes("HYDRATION_TTL_MS"), true);
  assert.equal(demo.includes("hydrateConnections().catch"), false);
});

test("saved workflows are prefetched without running historical repair first", () => {
  const history = readFileSync(new URL("../src/components/aura/HistoryPanel.jsx", import.meta.url), "utf8");
  assert.equal(history.includes("savedHistoryPromise"), true);
  assert.equal(history.indexOf("loadSavedHistory().then") < history.indexOf("reconcileDurableHistory(saved.workflows"), true);
});
