import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { build } from "vite";
import { executeMarketingSimulation } from "../src/lib/marketingToolSimulation.mjs";

const repo = fileURLToPath(new URL("../", import.meta.url));
let temporary;
let render;
let renderToolWorkspace;
let renderSheetReview;
let renderSheetCard;
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
          export function ensureWorkspace() { throw new Error("Render tests cannot access workspaces"); }
          export function auraRequest() { throw new Error("Render tests cannot access support APIs"); }
          export function createWorkflowSchedule() { throw new Error("Render tests cannot execute workflows"); }
          export function getPythonRun() { throw new Error("Render tests cannot read live workflows"); }`;
      },
    }],
    build: { ssr: path.join(repo, "tests/fixtures/resultsRender.jsx"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "render.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  ({ render, renderToolWorkspace, renderSheetReview, renderSheetCard } = await import(pathToFileURL(path.join(temporary, "render.mjs"))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

test("the main Sheet screen exposes both editing routes and preserves read-only review contracts", () => {
  const args = { spreadsheet_id: "target", range: "'Comparison'!A1:B1000", values: [["Brand", "$70"]] };
  const html = renderSheetCard(args);
  for (const text of ["Main output", "Ask AURA", "Edit manually", "View in tool", "Google Sheets action preview", "Markdown comparison", "Not saved yet"]) assert.ok(html.includes(text), text);
  assert.doesNotMatch(renderSheetCard(args, false), /Ask AURA|Edit manually/);
});

test("spreadsheet approval shows actual prepared cells and completed ChatGPT output without claiming a write", () => {
  const activity = [{ id: "analysis", tool: "AURA Intelligence", operation: "report.compose", status: "completed",
    output: { operation: "report.compose", critic: { action: "accept" }, outcome_check: { status: "verified" },
      provider_result: { status: "draft", title: "Competitor comparison", body: "## Comparison\n\n| Brand | Price |\n|---|---|\n| Example | $70 / 30 ml |" } } },
    { id: "headers", tool: "Google Sheets", operation: "sheets.read", status: "completed", output: { operation: "sheets.read",
      provider_result: { spreadsheetId: "target-sheet", range: "'Competitor Comparison'!A1:B1", values: [["Brand", "Current price"]] } } }];
  const args = { spreadsheet_id: "target-sheet", range: "'Competitor Comparison'!A:B", values: [["Example", "$70 / 30 ml"], ["Other", "Unavailable"]] };
  const html = renderSheetReview(args, activity);
  for (const text of ["ChatGPT prepared output", "ChatGPT comparison", "Google Sheets action preview", "Current price", "$70 / 30 ml", "Unavailable", "2 new rows", "Not saved yet", "A · new row 1"]) assert.ok(html.includes(text), text);
  assert.ok(html.indexOf("ChatGPT prepared output") < html.indexOf("Google Sheets action preview"));
  assert.doesNotMatch(html, /Saved and verified|Complete saved cell|<textarea|AURA Intelligence/);
  assert.match(renderSheetReview(args, activity, true), /<textarea/);
  assert.doesNotMatch(renderSheetReview(args, activity, true, false), /<textarea/);
  assert.doesNotMatch(renderSheetReview(args, [{ ...activity[0], status: "failed" }]), /ChatGPT prepared output|Response ready/);
});

test("the marketing results summarize actual execution and keep each tool output behind its own view", async () => {
  const simulations = await Promise.all(["meta", "klaviyo"].map(tool => executeMarketingSimulation(tool, {simulate:true, scenario:"maple_ember_v1"})));
  const steps = [
    {id:"g",tool_slug:"google-ads",operation:"google-ads.list-account-id-options",status:"completed",output:{operation:"google-ads.list-account-id-options",provider_result:{options:[]}}},
    {id:"m",tool_slug:"mailchimp",operation:"mailchimp.audiences.list",status:"failed",error:"Audience unavailable"},
    ...simulations.map((packet,index)=>({id:`sim-${index}`,tool_slug:index ? "klaviyo-simulated" : "meta-ads-simulated",operation:packet.receipt.operation,status:"completed",output:{operation:packet.receipt.operation,provider_result:packet}})),
  ];
  const html = render({id:"hybrid",status:"completed",plan:{name:"Hybrid marketing review"},steps});
  assert.match(html,/aria-label="Marketing workflow results"/);
  for (const tool of ["Google Ads", "Meta Ads", "Mailchimp", "Klaviyo"]) assert.ok(html.includes(tool));
  for (const text of ['Marketing campaign review ready','native checks completed','simulated tool outputs','launches or sends','What happened','Tools used','the actual output','Suggested next','Review approvals','Client matching']) assert.ok(html.includes(text),text);
  assert.match(html,/View Meta Ads output/);
  assert.match(html,/View Klaviyo output/);
  assert.match(html,/Needs attention/);
  assert.doesNotMatch(html,/Simulated weekly performance|Campaign report sent|time saved/);
  assert.doesNotMatch(html,/AURA Intelligence output preview|report\.compose|weekly\.source\.analyze/);
  for (const key of ['google','meta','mailchimp','klaviyo']) {
    const output=renderToolWorkspace({simulations},steps,key);
    const name={google:'Google Ads',meta:'Meta Ads',mailchimp:'Mailchimp',klaviyo:'Klaviyo'}[key];
    assert.ok(output.includes(`aria-label="${name} output"`));
    assert.doesNotMatch(output,/<h1/);
    assert.ok(output.includes(`aria-label="${name} interface preview"`));
    assert.match(output,/Interface imitation|Simulated interface/);
    if(key==='meta') for(const text of ['Simulated weekly performance','Campaigns','Cost per purchase','Source rows and execution receipt']) assert.ok(output.includes(text));
    if(key==='klaviyo') for(const text of ['Abandoned checkout','Repeat-purchase replenishment','vendor API was not called','Source rows and execution receipt']) assert.ok(output.includes(text));
    if(key==='mailchimp') assert.match(output,/Audience unavailable/);
    if(key==='google') assert.match(output,/Account selection required/);
  }
  const metaAds=renderToolWorkspace({simulations},steps,'meta','ads');
  for(const text of ['Coffee detail static','Morning brew video','not saved in Meta','Primary text','Facebook Feed','Your First House Blend: 10% Off']) assert.ok(metaAds.includes(text),text);
  const analytics=renderToolWorkspace({simulations},steps,'klaviyo','analytics');
  for(const text of ['Flow performance','Attributed revenue','Checkout follow-up | 4 hours','5-day click / 1-day open']) assert.ok(analytics.includes(text),text);
  const evidence=renderToolWorkspace({simulations},steps,'meta','evidence');
  assert.match(evidence,/fixture_sha256/);
  assert.match(evidence,/browser_simulated_tool_adapter/);
});

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

test("the main output precedes supporting actions and tools", () => {
  const html = render(run);
  const main = html.indexOf('aria-label="Main workflow result"');
  const actions = html.indexOf('aria-label="Supporting workflow actions"');
  const tools = html.indexOf('aria-label="Results by tool"');
  assert.ok(main > 0 && main < actions && actions < tools);
  assert.match(html, /<details aria-label="Main workflow result" class="group mb-6">/);
  const content = html.slice(main, html.indexOf("What would you like to do next?"));
  for (const text of ["Sourced campaign brief", "Get a Free Estimate", "Final review remains pending."]) assert.ok(content.includes(text));
  assert.match(content, /href="https:\/\/example.com\/roofing"/);
  assert.doesNotMatch(content, /Fictional demonstration/);
  assert.match(html, /What happened/);
  assert.match(html, /View action/);
  assert.match(html, /Tools used/);
  assert.match(html, /View activity/);
  assert.match(content, /Google Docs output preview/);
  assert.match(content, /Open tool view/);
  assert.match(content, /max-h-\[30rem\]/);
  assert.match(html, /aria-label="View Google Ads results"/);
  assert.doesNotMatch(html.slice(tools), /<details[^>]*\bopen(?:=|[ >])/);
});

test("a blocked run retains actual saved content and failed action evidence without a completion claim", () => {
  const html = render({ ...run, status: "waiting_for_action", steps: [proposal,
    { ...keywords, status: "blocked", output: undefined, error: "Account access is missing" }],
  });
  assert.match(html, /incomplete/);
  assert.match(html, /has not completed/);
  assert.match(html, /Final review remains pending/);
  assert.match(html, /1 action needs/);
  assert.match(html, /aria-label="View Google Ads results"/);
  assert.doesNotMatch(html, /Workflow complete<\/|Schedule<\/button>/);
});

test("a primary provider read shows its returned rows in the tool screen rather than the workflow summary", () => {
  const html = render({ ...run, steps: [keywords], result: { result_presentation: { primary_step_key: "keywords" } } });
  assert.match(html, /Google Ads output preview/);
  assert.match(html, /roof repair/);
  assert.match(html, /Open tool view/);
  assert.doesNotMatch(html, /Google Docs output preview/);
});

test("an unavailable main output does not create an empty tool preview", () => {
  const html = render({ ...run, status: "waiting_for_action", steps: [{ ...keywords, status: "blocked", output: undefined }], result: {} });
  assert.doesNotMatch(html, /output preview|Open tool view/);
  assert.match(html, /View Google Ads results/);
});

test("the visible Results section leads with final Sheets cells, exact link and ChatGPT attribution", () => {
  const sheetSteps = [
    { id: "source", key: "source", tool_slug: "google", status: "completed", output: { operation: "sheets.read", resolved_arguments: { spreadsheet_id: "workbook" }, provider_result: { range: "'Source'!A1:B2", values: [["Earlier source"]] } } },
    { id: "compose", key: "compose", tool_slug: "aura", status: "completed", output: { operation: "report.compose", provider_result: { body: "Generated report" } } },
    { id: "saved", key: "saved", tool_slug: "google", status: "completed", output: { operation: "sheets.append", provider_result: { spreadsheetId: "workbook", updates: { updatedRange: "'Pilot Record'!A49:B52" } }, outcome_check: { status: "verified", observed: { spreadsheetId: "workbook", sheets: [{ properties: { title: "Pilot Record", sheetId: 77 }, data: [{ startRow: 48, rowData: [{ values: [{ effectiveValue: { stringValue: "Actual final cells" } }] }] }] }] } } } },
  ];
  const html = render({ id: "sheet-run", status: "completed", plan: { name: "Pilot result" }, steps: sheetSteps, result: { result_presentation: { primary_step_key: "saved" } } });
  assert.match(html, /Google Sheets result screen/);
  assert.match(html, /Saved Google Sheets cells/);
  assert.match(html, /Actual final cells/);
  assert.match(html, /https:\/\/docs.google.com\/spreadsheets\/d\/workbook\/edit#gid=77&amp;range=A49%3AB52/);
  assert.doesNotMatch(html, /<iframe/);
  assert.match(html, /Saved cells/);
  assert.match(html, /Report saved to Google Sheets/);
  assert.match(html, /source tab read in Google Sheets/);
  assert.match(html, /report prepared with ChatGPT/);
  assert.match(html, /rows saved to Google Sheets/);
  assert.match(html, /<section aria-label="Main workflow result" class="group mb-6">/);
  assert.ok(html.indexOf('aria-label="Main workflow result"') < html.indexOf('aria-label="Results by tool"'));
  assert.match(html, /aria-label="View ChatGPT results"/);
  assert.doesNotMatch(html, /AURA Intelligence|Earlier source|majorDimension|~12 min|time saved|Campaign report sent/);
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
  assert.match(html, /aria-label="View ChatGPT results"/);
});

test("a completed campaign stays native in AURA with channel views and actual per-tool evidence", () => {
  const campaignBody = ["Campaign brief", "Google Search drafts", "Facebook and Instagram drafts",
    "Google Business Profile draft", "Indoor screen draft", "Asset checklist", "Approval tracker and implementation handoff"]
    .map((heading) => `## ${heading}\n${"Saved draft copy with pending client approvals. ".repeat(4)}`).join("\n\n");
  const html = render({ ...run, steps: [proposal, keywords,
    { id: "compose", key: "compose", status: "completed", tool_slug: "AURA", output: {
      operation: "report.compose", critic: { action: "accept" }, outcome_check: { status: "verified" },
      provider_result: { status: "draft", title: "Unpublished campaign package", body: campaignBody,
        summary: "Campaign prepared inside AURA.", synthetic: false, sources: [] },
    } }], result: { result_presentation: { primary_step_key: "compose", metrics: [] } } });
  const main = html.slice(html.indexOf('aria-label="Main workflow result"'), html.indexOf("What would you like to do next?"));
  assert.match(main, /aria-label="Campaign launch package"/);
  for (const label of ["Google Ads", "Social ads", "Business Profile", "Indoor screens", "Assets", "Approvals and handoff", "Tool outputs"]) assert.ok(main.includes(label));
  assert.match(main, /Saved draft copy with pending client approvals/);
  assert.doesNotMatch(main, /Open in Google Docs|Checked in Google Docs/);
  assert.match(html, /Read keyword ideas/);
  assert.match(html, /aria-label="View Google Ads results"/);
});

test("a scoped booking campaign shows saved GBP, Meta and Reel views without excluded channels", () => {
  const campaignBody = ["Campaign brief", "Google Business Profile posts", "Meta ad variations", "15-second Reel",
    "Vagaro booking destination", "Asset checklist", "Approval table", "Implementation handoff"]
    .map((heading) => `## ${heading}\n${"Unpublished copy with client approval pending. ".repeat(4)}`).join("\n\n");
  const html = render({ ...run, steps: [{ id: "compose", key: "compose", status: "completed", tool_slug: "AURA", output: {
    operation: "report.compose", critic: { action: "accept" }, outcome_check: { status: "verified" },
    provider_result: { status: "draft", title: "Local booking campaign", body: campaignBody,
      summary: "Unpublished review package.", synthetic: false, sources: [] },
  } }], result: { result_presentation: { primary_step_key: "compose", metrics: [] } } });
  const main = html.slice(html.indexOf('aria-label="Main workflow result"'), html.indexOf("What would you like to do next?"));
  for (const label of ["Social ads", "Business Profile", "Reel", "Booking and source checks", "Assets", "Approvals and handoff", "Tool outputs"]) assert.ok(main.includes(label));
  assert.doesNotMatch(main, /Google Ads|Indoor screens|Open in Google Docs/);
  assert.match(main, /Complete saved report and source evidence/);
});
