import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { build } from "vite";

const repo = fileURLToPath(new URL("../", import.meta.url));
let temporary;
let render;
before(async () => {
  temporary = fs.mkdtempSync(path.join(repo, ".results-render-"));
  await build({
    configFile: path.join(repo, "vite.config.js"), logLevel: "silent",
    resolve: { alias: [
      { find: "@/api/base44Client", replacement: "\0no-account-access" },
      { find: "@/lib/auraApi", replacement: "\0no-account-access" },
      { find: "@", replacement: path.join(repo, "src") },
    ] },
    plugins: [{ name: "no-account-access-in-render-tests",
      enforce: "pre",
      resolveId(source) {
        if (["@/api/base44Client", "@/lib/auraApi"].includes(source)) return "\0no-account-access";
      },
      load(id) {
        if (id === "\0no-account-access") return `export const base44 = {};
          export function createWorkflowSchedule() { throw new Error("Render tests cannot execute workflows"); }
          export function getPythonRun() { throw new Error("Render tests cannot read live workflows"); }`;
      },
    }],
    build: { ssr: path.join(repo, "tests/fixtures/resultsRender.jsx"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "render.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  ({ render } = await import(pathToFileURL(path.join(temporary, "render.mjs"))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

const body = `## Sourced campaign brief
Roof repairs and replacements. [Business source](https://example.com/roofing)

## Proposed copy
Get a Free Estimate.

## Implementation handoff
Final review remains pending.`;
const proposal = { id: "proposal-read", key: "proposal", tool_slug: "Google Docs",
  status: "completed", operation: "google-docs.get-document", reason: "Read the saved proposal",
  output: { operation: "google-docs.get-document", provider_result: {
    ret: { documentId: "proposal-doc", title: "Roofing campaign proposal", textContent: body },
  } },
};
const keywords = { id: "keyword-read", key: "keywords", tool_slug: "Google Ads",
  status: "completed", operation: "google-ads.generate-keyword-ideas", reason: "Read keyword ideas",
  output: { operation: "google-ads.generate-keyword-ideas", provider_result: { ret: [{ text: "roof repair" }] } },
};
const run = { id: "saved-run", status: "completed", plan: { name: "Roofing campaign proposal" },
  steps: [proposal, keywords], result: { result_presentation: {
    primary_step_key: "proposal", supporting_step_keys: ["keywords"], metrics: [],
  } },
};

test("the existing results page displays the full proposal before supporting actions and activity", () => {
  const html = render(run);
  const main = html.indexOf('aria-label="Main workflow result"');
  const actions = html.indexOf('aria-label="Supporting workflow actions"');
  const tools = html.indexOf('aria-label="Results by tool"');
  assert.ok(main > 0 && main < actions && actions < tools);
  const content = html.slice(main, actions);
  for (const text of ["Sourced campaign brief", "Get a Free Estimate", "Final review remains pending."]) assert.ok(content.includes(text));
  assert.match(content, /href="https:\/\/example.com\/roofing"/);
  assert.doesNotMatch(content, /<details|Fictional demonstration/);
  assert.match(html, /What happened/);
  assert.match(html, /View action/);
  assert.match(html, /Tools used/);
  assert.match(html, /View activity/);
  assert.doesNotMatch(html.slice(tools), /<details[^>]*\bopen(?:=|[ >])/);
});

test("a blocked run retains actual saved content and failed action evidence without a completion claim", () => {
  const html = render({ ...run, status: "waiting_for_action", steps: [proposal,
    { ...keywords, status: "blocked", output: undefined, error: "Account access is missing" }],
  });
  assert.match(html, /incomplete/);
  assert.match(html, /has not completed/);
  assert.match(html, /Final review remains pending/);
  assert.match(html, /Account access is missing/);
  assert.match(html, /No provider response is saved/);
  assert.doesNotMatch(html, /Workflow complete<\/|Schedule<\/button>/);
});

test("a supplied-evidence report renders its complete body without implying provider execution", () => {
  const html = render({ ...run, steps: [{ id: "compose", key: "compose", status: "completed", tool_slug: "AURA", output: {
    operation: "report.compose", critic: { action: "accept" }, outcome_check: { status: "verified" },
    provider_result: { status: "draft", title: "Review proposal", summary: "Prepared from supplied evidence.",
      body, synthetic: false, sources: [{ id: "brief", title: "Provided brief", content: "Supplied source only." }] },
  } }], result: {} });
  assert.match(html, /Prepared from supplied evidence/);
  assert.match(html, /Final review remains pending/);
  assert.match(html, /Supplied source inputs/);
  assert.match(html, /A connection alone is not a completed tool run/);
});
