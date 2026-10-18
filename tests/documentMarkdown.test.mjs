import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import { documentMarkdownOptions } from "../src/lib/documentMarkdown.mjs";

const render = (children) => renderToStaticMarkup(React.createElement(
  ReactMarkdown, { ...documentMarkdownOptions, children },
));

test("review tables preserve headers, missing values, sources and action cells", () => {
  const html = render(`| Metric | Current | Source |
|---|---|---|
| Leads | NV | M3 |
| Appointments | NV | M3 |

| Action | Owner | Due |
|---|---|---|
| Collect inputs | Account lead | 19 Oct 2026 |`);
  assert.equal((html.match(/<table>/g) || []).length, 2);
  assert.match(html, /<th>Current<\/th>/);
  assert.match(html, /<td>NV<\/td>/);
  assert.match(html, /<td>Account lead<\/td>/);
  assert.match(html, /role="region" aria-label="Document table" tabindex="0"/);
});

test("table rendering keeps active HTML and unsafe links inert", () => {
  const html = render(`| Source | Value |
|---|---|
| <script>alert(1)</script> | [click](javascript:alert) |`);
  assert.doesNotMatch(html, /<script>|href="javascript:/);
  assert.match(html, /&lt;script&gt;/);
});
