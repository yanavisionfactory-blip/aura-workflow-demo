import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("the browser tab uses AURA branding without a third-party asset", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const favicon = readFileSync(new URL("../public/aura-favicon.svg", import.meta.url), "utf8");

  assert.match(html, /<title>AURA — Autonomous Workflow Assistant<\/title>/);
  assert.match(html, /href="\.\/aura-favicon\.svg"/);
  assert.equal(html.includes("base44.com/logo"), false);
  assert.match(favicon, /<svg/);
});
