import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import data from "../public/showcase/seo-audit/data.mjs";
import { initialState, nextState, renderFrame, tour, originalPrompt } from "../public/showcase/seo-audit/view.mjs";

test("public showcase keeps observed counts and source rows, but excludes credentials and private source attachments", () => {
  assert.equal(data.anonymized, true);
  assert.equal(data.backend, false);
  assert.equal(data.crawl.counts.url_records, 171);
  assert.equal(data.crawl.counts.canonical_conflicts, 82);
  assert.equal(data.crawl.counts.indexable_html, 4);
  assert.equal(data.crawl.counts.link_edge_rows, 0);
  assert.equal(data.backlog.length, 10);
  assert.equal(data.crawl.issues.find((issue) => issue.id === "T01").affected.length, 82);
  assert.equal(data.crawl.files[1].duplicate_of, data.crawl.files[0].filename);
  const serialized = JSON.stringify(data);
  assert.doesNotMatch(serialized, /data:text\/csv|oauth_access_token|api_key|workspace_id|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/i);
  for (const row of data.crawl.issues.flatMap((issue) => issue.affected)) {
    if (row.url) assert.equal(new URL(row.url).hostname, "client.example");
    assert.ok(Number.isInteger(row.csv_row));
  }
  for (const tool of data.tools) { assert.equal(tool.simulated, true); assert.equal(tool.state, "simulated"); assert.deepEqual(tool.actions, []); }
});

test("one workflow can be explored through all tool outputs, URL pagination, groups and full backlog items", () => {
  let state = { ...initialState };
  state = nextState(state, "plan", data); assert.equal(state.phase, "plan");
  state = nextState(state, "results", data); assert.equal(state.phase, "results");
  for (const tool of ["crawl", "semrush", "ahrefs", "sitebulb"]) {
    state = nextState(state, `tool:${tool}`, data);
    assert.equal(state.tool, tool);
    assert.match(renderFrame(data, state), /output/);
  }
  state = nextState(state, "tool:crawl", data);
  const first = renderFrame(data, state);
  state = nextState(state, "next-page", data);
  assert.notEqual(renderFrame(data, state), first);
  assert.match(renderFrame(data, state), /7–12 of 82 real findings/);
  state = nextState(state, "group:Content", data);
  assert.equal(state.group, "Content");
  assert.ok(data.backlog.some((item) => item.id === state.task && item.group === "Content"));
  state = nextState(state, "task:C01", data);
  assert.match(renderFrame(data, state), /SIMULATED RECOMMENDATION/);
  assert.match(renderFrame(data, { ...initialState, phase: "backlog" }), /REAL CRAWL EVIDENCE/);
  assert.equal(nextState(state, "tool:javascript:alert(1)", data), state);
  assert.equal(nextState(state, "task:missing", data), state);
});

test("walkthrough uses the exact same screens and consistently discloses simulated research", () => {
  assert.equal(tour.length * 6, 66);
  for (const scene of tour) {
    const svg = renderFrame(data, { ...initialState, ...scene.state }, { caption: scene.caption, chapter: "1 / 11", pointer: scene.pointer });
    assert.match(svg, /STATIC PROTOTYPE/);
    assert.match(svg, /1 real export · 3 simulated tools/);
    assert.match(svg, /data-action=/);
    assert.doesNotMatch(svg, /undefined|NaN|<script|<foreignObject/);
    assert.ok(!scene.caption.includes("successfully connected"));
  }
  const semrush = renderFrame(data, { ...initialState, phase: "tool", tool: "semrush" });
  assert.match(semrush, /SIMULATED OUTPUT/);
  const sitebulb = renderFrame(data, { ...initialState, phase: "tool", tool: "sitebulb" });
  assert.match(sitebulb, /HYPOTHETICAL/);
  assert.match(sitebulb, /No Sitebulb crawl was performed/);
  assert.ok(originalPrompt.startsWith("Prepare an SEO audit review package for one Mantas Auk client."));
  assert.ok(originalPrompt.endsWith("Do not modify the website."));
});

test("standalone entry loads directly and forbids account or tool network requests", () => {
  const base = new URL("../public/showcase/seo-audit/", import.meta.url);
  const html = fs.readFileSync(new URL("index.html", base), "utf8");
  const app = fs.readFileSync(new URL("app.mjs", base), "utf8");
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /No account needed/);
  assert.match(html, /src="\.\/walkthrough.mp4"/);
  assert.match(html, /type="module" src="\.\/app.mjs"/);
  assert.doesNotMatch(app, /\bfetch\s*\(|XMLHttpRequest|WebSocket|Clerk|auraApi|google-analytics|localStorage/);
  assert.match(app, /navigator.clipboard.writeText/);
  assert.match(app, /keydown/);
  const video = fs.readFileSync(new URL("walkthrough.mp4", base));
  assert.ok(video.includes(Buffer.from("ftyp")));
  assert.ok(video.length > 100_000);
  assert.deepEqual([...fs.readFileSync(new URL("poster.png", base)).subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.match(fs.readFileSync(new URL("walkthrough.vtt", base), "utf8"), /00:01:00.000 --> 00:01:06.000/);
});
