import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { build } from "vite";
import { executeMarketingSimulation } from "../src/lib/marketingToolSimulation.mjs";
import { frameioOutputs } from "./fixtures/frameioReview.mjs";
import { resolvedApprovalStep } from "../src/lib/approvalReview.mjs";
import { JSDOM } from "jsdom";
import React, { act } from "react";
import { rows as planteaRows } from "../public/showcase/mason-green/data.mjs";

const repo = fileURLToPath(new URL("../", import.meta.url));
let temporary;
let render;
let renderToolWorkspace;
let renderSheetReview;
let renderSheetCard;
let renderActionScreen;
let renderApproval;
let renderExecution;
let renderPlan;
let ResultsTestView;
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
          export function getPythonRun() { throw new Error("Render tests cannot read live workflows"); }
          export const pythonRuntimeEnabled = false;
          ${["authorizeConnectorBroker", "disconnectPythonConnection", "getManagedConnectorStatus", "listPythonTools", "listGoogleAdsAccounts", "selectGoogleAdsAccount", "listRedditAdsAccounts", "selectRedditAdsAccount", "reserveAuthorizationWindow", "searchConnectorBrokerApps", "testPythonConnection"].map((name) => `export function ${name}() { throw new Error("Render tests cannot access connections"); }`).join("\n")}`;
      },
    }],
    build: { ssr: path.join(repo, "tests/fixtures/resultsRender.jsx"), outDir: temporary,
      emptyOutDir: true, rollupOptions: { output: { entryFileNames: "render.mjs" } } },
    ssr: { noExternal: ["lucide-react"] },
  });
  ({ render, renderToolWorkspace, renderSheetReview, renderSheetCard, renderActionScreen, renderApproval, renderExecution, renderPlan, ResultsTestView } = await import(pathToFileURL(path.join(temporary, "render.mjs"))));
});
after(() => { if (temporary) fs.rmSync(temporary, { recursive: true, force: true }); });

test("Frame.io review keeps its editable brief without the removed change composer", () => {
  const steps = frameioOutputs().map((output) => ({ id: output.step_id || output.step_key, key: output.step_key,
    tool_slug: output.operation.startsWith("frameio") ? "frameio" : "aura", operation: output.operation,
    status: "completed", reason: output.operation, output }));
  const html = render({ id: "frameio-review", status: "completed", plan: { name: "Review campaign" }, steps,
    result: { result_presentation: { primary_step_key: "brief" } } });
  for (const text of ["Frame.io review workspace", "Campaign cut.mp4", "Revision brief", "Edit brief", "Comments (0)",
    "Human review pending", "View Frame.io results", "View ChatGPT results"]) assert.ok(html.includes(text), text);
  assert.ok(html.indexOf("Frame.io review workspace") < html.indexOf("Supporting workflow actions"));
  assert.doesNotMatch(html, /Google Docs|Google Sheets|<iframe|Approved content/);
  assert.match(html, /<details[^>]*><summary[^>]*>File details/);
  assert.match(html, /Open in Frame.io/);
  assert.doesNotMatch(html, /What would you like to change|Change result with a prompt/);
});

test("result review shows completed output on its own page without previews for pending steps", () => {
  const pending = { id: "save", tool: "Google Sheets", operation: "sheets.append", action: "Save dashboard", status: "pending" };
  const before = renderExecution([pending]);
  assert.doesNotMatch(before, /output preview|Saved Google Sheets cells|Tool result review/);
  const draft = { id: "draft", key: "draft", tool: "Claude", operation: "anthropic.chat", action: "Prepare comparison", status: "completed",
    output: { operation: "anthropic.chat", critic: { action: "accept" }, outcome_check: { status: "verified" },
      provider_result: { ret: { content: [{ type: "text", text: "## September 2026\nRevenue, targets and actuals." }] } } } };
  const html = renderExecution([draft, pending], { step_id: "draft", step_ids: ["draft"], tool_slug: "anthropic", operation: "anthropic.chat", next_tool_slug: "google", next_operation: "sheets.append", is_final: false });
  for (const text of ["Tool result review", "Review Claude result", "September 2026", "Revenue, targets and actuals.", "Approve result", "Your place is saved"]) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /Execution steps|Preview Claude|Continue to|Saved Google Sheets cells/);
  const final = renderExecution([draft], { step_id: "draft", step_ids: ["draft"], is_final: true });
  assert.match(final, /Approve and finish/);
});

test("completed preparation displays the saved response instead of the input prompt", () => {
  const planned = { key: "draft", tool: "Claude", operation: "anthropic.chat", riskLevel: "modify",
    arguments: { userMessage: "INPUT REQUEST MUST NOT LOOK LIKE THE RESULT" }, output: "Expected table" };
  const runtime = { id: "saved-draft", key: "draft", tool_slug: "anthropic", operation: "anthropic.chat",
    status: "completed", consequential: true, approval_status: "approved",
    output: { operation: "anthropic.chat", critic: { action: "accept" }, outcome_check: { status: "verified" }, provider_result: { ret: { content: [
      { type: "text", text: "## Plantéa — September 2026\nRevenue | Target | Actual" },
    ] } } } };
  const step = resolvedApprovalStep(planned, runtime, "Claude");
  assert.equal(step.riskLevel, "read");
  const html = renderActionScreen(step);
  assert.match(html, /Claude prepared output/);
  assert.match(html, /Plantéa — September 2026/);
  assert.doesNotMatch(html, /INPUT REQUEST|Ready to generate|Expected table|Not saved yet/);
  const failed = renderActionScreen(resolvedApprovalStep(planned, { ...runtime, status: "failed" }, "Claude"));
  assert.doesNotMatch(failed, /Claude prepared output|Plantéa — September 2026/);
});

test("all approval routes lead with app screens and keep technical settings collapsed", () => {
  const steps = [
    { tool: "Claude", operation: "anthropic.chat", action: "Prepare a dashboard", arguments: {
      model: "claude-test", userMessage: "Make a clean KPI dashboard for September 2026.", maxTokensToSample: 800,
    } },
    { tool: "Custom CRM", operation: "custom.create", action: "Create customer", arguments: { name: "Example customer", owner: "Account team" } },
    { tool: "Google Sheets", operation: "sheets.kpi.create", action: "Create dashboard", arguments: {
      business_name: "Plantéa", reporting_period: "September 2026", illustrative: true, denominator: "sessions",
      target: { revenue: 1000, orders: 10, conversions: 4, denominator_value: 100 },
      actual: { revenue: 800, orders: 8, conversions: 0, denominator_value: 0 },
    } },
  ];
  const html = renderApproval(steps);
  for (const name of ["Claude", "Custom CRM", "Google Sheets"]) assert.ok(html.includes(`${name} action preview`));
  assert.match(html, /New conversation|Ready to generate/);
  assert.match(html, /KPI Dashboard/);
  assert.match(html, /Illustrative template values/);
  assert.match(html, /<details[^>]*><summary[^>]*>[\s\S]*?Action settings/);
  assert.doesNotMatch(html, /<details open|Additional details|NaN|Infinity/);
  assert.ok(html.indexOf("Claude action preview") < html.indexOf("Action settings"));
  const edited = renderActionScreen(steps[2], true);
  assert.match(edited, /aria-label="Revenue target"/);
  assert.match(edited, /aria-label="Business name"/);
  assert.doesNotMatch(renderActionScreen(steps[0]), /maxTokensToSample|claude-test|>800</);
});

test("backup results disclose the actual generator and preserve its saved response screen", () => {
  const message = "Claude's API account has insufficient credits. AURA Intelligence generated the content as the approved backup so the workflow could continue.";
  const html = render({ id: "backup", status: "completed", plan: { name: "KPI draft" }, steps: [{
    id: "draft", tool_slug: "aura", operation: "intelligence.claude_backup", status: "completed", reason: "Prepare KPI draft",
    output: { tool: "aura", operation: "intelligence.claude_backup", critic: { action: "accept" }, outcome_check: { status: "verified" },
      fallback: { status: "used", requested_tool: "anthropic", requested_operation: "anthropic.chat", actual_tool: "aura", actual_operation: "intelligence.claude_backup", message },
      provider_result: { ret: { content: [{ type: "text", text: "## September 2026\n\nRevenue, targets and actuals." }] } },
    },
  }] });
  for (const expected of ["Claude response", "Backup used", "insufficient credits", "September 2026", "Results from every tool", "Results by tool"]) assert.ok(html.includes(expected), expected);
  assert.ok(html.indexOf("Results from every tool") < html.indexOf("Claude response"));
  assert.match(html, /<details[^>]*aria-label="Claude result dropdown"/);
  assert.doesNotMatch(html, /Generated with Claude|AURA Intelligence output preview/);
  assert.match(html, /Backup used ·/);
});

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

test("the summary leads and every tool result is a dropdown inside Results from every tool", () => {
  const html = render(run);
  const doc = new JSDOM(html).window.document;
  const summary = doc.querySelector('[aria-label="Workflow summary"]');
  const outcomes = summary.querySelector('[aria-label="Supporting workflow actions"]');
  const tools = summary.querySelector('[aria-label="Results by tool"]');
  assert.equal(summary.parentElement.firstElementChild, summary);
  assert.equal(outcomes.nextElementSibling, tools);
  for (const name of ["Google Docs", "Google Ads"]) assert.ok(outcomes.querySelector(`details[aria-label="${name} result dropdown"]`));
  for (const text of ["Sourced campaign brief", "Get a Free Estimate", "Final review remains pending.", "roof repair"]) assert.ok(outcomes.textContent.includes(text));
  assert.match(html, /href="https:\/\/example.com\/roofing"/);
  assert.doesNotMatch(html, /Main workflow result|Other tool outputs|What would you like to change|Change result with a prompt|Fictional demonstration/);
  assert.match(html, /View activity/);
  assert.match(html, /aria-label="View Google Ads results"/);
  const openDetails = [...doc.querySelectorAll("details[open]")];
  assert.equal(openDetails.length, 0, "saved data screens are visible above collapsed action history");
  assert.match(outcomes.querySelector('[aria-label="Google Ads result screen"]').textContent, /roof repair/);
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
  assert.match(html, /Google Ads result dropdown/);
  assert.match(html, /roof repair/);
  assert.match(html, /<details[^>]*aria-label="[^"]+ result dropdown"/);
  assert.doesNotMatch(html, /Google Docs output preview/);
});

test("an unavailable main output does not create an empty tool preview", () => {
  const html = render({ ...run, status: "waiting_for_action", steps: [{ ...keywords, status: "blocked", output: undefined }], result: {} });
  assert.doesNotMatch(html, /output preview|Open tool view/);
  assert.match(html, /View Google Ads results/);
});

test("the expandable Results section contains final Sheets cells, exact link and ChatGPT attribution", () => {
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
  assert.match(html, /source tab read/);
  assert.match(html, /Generated report/);
  assert.match(html, /rows saved/);
  assert.match(html, /<details[^>]*aria-label="[^"]+ result dropdown"/);
  assert.ok(html.indexOf('aria-label="Google Sheets result screen"') < html.indexOf('aria-label="Results by tool"'));
  assert.match(html, /aria-label="View ChatGPT results"/);
  const cells = new JSDOM(html).window.document.querySelector('[aria-label="Saved Google Sheets cells"]');
  assert.doesNotMatch(cells.textContent, /Earlier source/);
  assert.doesNotMatch(html, /AURA Intelligence|~12 min|time saved|Campaign report sent/);
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
  const main = html.slice(html.indexOf('aria-label="Supporting workflow actions"'), html.indexOf("What would you like to do next?"));
  assert.match(main, /aria-label="Campaign launch package"/);
  for (const label of ["Google Ads", "Social ads", "Business Profile", "Indoor screens", "Assets", "Approvals and handoff", "Tool outputs"]) assert.ok(main.includes(label));
  assert.match(main, /Saved draft copy with pending client approvals/);
  const campaign = new JSDOM(html).window.document.querySelector('[aria-label="Campaign launch package"]');
  assert.doesNotMatch(campaign.textContent, /Open in Google Docs|Checked in Google Docs/);
  assert.match(main, /<details[^>]*aria-label="Google Docs result dropdown"/);
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
  const main = html.slice(html.indexOf('aria-label="Supporting workflow actions"'), html.indexOf("What would you like to do next?"));
  for (const label of ["Social ads", "Business Profile", "Reel", "Booking and source checks", "Assets", "Approvals and handoff", "Tool outputs"]) assert.ok(main.includes(label));
  assert.doesNotMatch(main, /Google Ads|Indoor screens|Open in Google Docs/);
  assert.match(main, /Complete saved report and source evidence/);
});


test("plans show steps without tool previews, including older saved plans", () => {
  for (const steps of [[
    { tool: "Claude", title: "Prepare KPI comparison", operation: "anthropic.chat", arguments: { userMessage: "Create dashboard" }, riskLevel: "read" },
    { tool: "Google Sheets", title: "Save KPI dashboard", operation: "sheets.append", riskLevel: "modify" },
  ], [{ tool: "frameio", title: "Read the saved file and comments", output: "Review feedback" }]]) {
    const html = renderPlan(steps);
    assert.match(html, /KPI dashboard/);
    assert.doesNotMatch(html, /Tool workspace preview|Preview by tool|action preview|output preview|Your selected file|<video/);
  }
});


test("final results show both tool screens, with the Sheet ahead of the Claude step", () => {
  const steps = [
    { id: "draft", key: "draft", tool_slug: "aura", operation: "intelligence.claude_backup", status: "completed", reason: "Prepare comparison", output: {
      step_id: "draft", operation: "intelligence.claude_backup", critic: { action: "accept" }, outcome_check: { status: "verified" },
      fallback: { status: "used", requested_tool: "anthropic", requested_operation: "anthropic.chat", actual_tool: "aura", actual_operation: "intelligence.claude_backup",
        message: "Claude had insufficient credits. AURA Intelligence completed the step." },
      provider_result: { ret: { content: [{ type: "text", text: "Full saved KPI comparison from the drafting step." }] } },
    } },
    { id: "saved", key: "saved", tool_slug: "google", status: "completed", output: { step_id: "saved", operation: "sheets.append",
      provider_result: { spreadsheetId: "dashboard", updates: { updatedRange: "KPIs!A1:C2" } },
      outcome_check: { status: "verified", observed: { range: "KPIs!A1:C2", values: [["Metric", "Target", "Actual"], ["Revenue", "", ""]] } } } },
  ];
  const html = render({ id: "kpi", status: "completed", plan: { name: "September 2026 KPIs" }, steps, result: { result_presentation: { primary_step_key: "draft" } } });
  const sheet = html.indexOf('aria-label="Google Sheets result screen"');
  const claude = html.indexOf('aria-label="Claude response"');
  assert.ok(sheet > 0 && claude > sheet);
  assert.match(html, /Full saved KPI comparison from the drafting step/);
  assert.match(html, /Backup used/);
  assert.doesNotMatch(html, /AURA Intelligence output preview|Generated with Claude/);
  assert.match(html, /Backup used ·/);
});


test("broker Sheets result review shows the workbook screen with technical receipts collapsed", () => {
  const step = { id: "saved", key: "save", tool: "Google Sheets", tool_slug: "google-sheets",
    operation: "google-sheets.add-multiple-rows", action: "Draft the content", status: "completed",
    output: { resolved_arguments: { sheetId: "broker-workbook", worksheetId: 173, rows: '[["Requested only"]]' },
      provider_result: { os: [], ret: { spreadsheetId: "broker-workbook", updatedRange: "Dashboard!A1:G8",
        updatedRows: 8, updatedColumns: 7, updatedCells: 56 },
        exports: { $summary: "Successfully updated 8 row(s) in the spreadsheet." } } } };
  const html = renderExecution([step], { step_id: step.id, step_ids: [step.id],
    tool_slug: "google-sheets", operation: step.operation, is_final: true });
  const visible = html.replace(/<details\b[^>]*>[\s\S]*?<\/details>/g, "");
  for (const text of ["Review Google Sheets result", "Google Sheets result screen", "Open in Google Sheets",
    "No saved cell data is available", "Approve and finish"]) assert.ok(visible.includes(text), text);
  assert.match(visible, /href="https:\/\/docs.google.com\/spreadsheets\/d\/broker-workbook\/edit#gid=173&amp;range=A1%3AG8"/);
  assert.doesNotMatch(visible, /<iframe/);
  assert.doesNotMatch(visible, /Empty list returned|spreadsheetId|updatedRange|updatedRows|updatedColumns|updatedCells|>ret<|>os<|Requested only/);
  assert.match(html, /<details[^>]*><summary[^>]*>Technical details<\/summary>/);
  assert.doesNotMatch(html, /<details[^>]*\bopen(?:=|>)/);
  assert.ok(html.indexOf("No saved cell data is available") < html.indexOf("Technical details"));
  assert.doesNotMatch(html, /<button[^>]*disabled[^>]*>[^<]*Approve and finish/);

  const final = render({ id: "broker-run", status: "completed", plan: { name: "KPI dashboard" },
    steps: [step], result: { result_presentation: { primary_step_key: "save" } } });
  assert.match(final, /Google Sheets result screen/);
  assert.doesNotMatch(final, /<iframe/);
  assert.match(final, /No saved cell data is available/);
  assert.match(final, /Open in Google Sheets/);
});

test("broker saved-cell readback renders a spreadsheet grid without depending on embedded Google sign-in", () => {
  const step = { id: "saved", key: "save", tool: "Google Sheets", tool_slug: "google-sheets",
    operation: "google-sheets.update-row", status: "completed",
    output: { provider_result: { ret: { spreadsheetId: "broker-workbook", updatedRange: "Dashboard!A1:C2" } },
      outcome_check: { status: "verified", observed: { ret: { range: "Dashboard!A1:C2",
        values: [["Metric", "Target", "Actual"], ["Revenue", "", ""]] } } } } };
  const html = renderExecution([step], { step_id: step.id, step_ids: [step.id],
    tool_slug: "google-sheets", operation: step.operation, is_final: true });
  assert.match(html, /Saved Google Sheets cells/);
  assert.match(html, /Revenue/);
  assert.match(html, /Open in Google Sheets/);
  assert.doesNotMatch(html, /<iframe/);
});

test("an incomplete broker workflow summarizes completed work and previews the exact evaluated sheet readback", () => {
  const steps = [
    { id: "web", key: "web", tool_slug: "web", status: "completed", output: { operation: "web.page.read", provider_result: { url: "https://example.com/", text: "Retrieved source" } } },
    { id: "report", key: "report", tool_slug: "aura", status: "completed", output: { operation: "report.compose", provider_result: { body: "Intermediate planning report" } } },
    { id: "save", key: "save", tool_slug: "google-sheets", operation: "google-sheets.update-multiple-rows", status: "completed",
      output: { resolved_arguments: { sheetId: "final-workbook", worksheetId: 173, rows: '[["Unsaved proposal"]]' },
        provider_result: { os: [], ret: { spreadsheetId: "final-workbook", updatedRange: "Dashboard!A1:G37", updatedRows: 37 } } } },
    { id: "verify", key: "verify", tool_slug: "google-sheets", operation: "google-sheets.read-rows", status: "completed",
      output: { resolved_arguments: { spreadsheetId: "final-workbook", sheetName: "Dashboard", range: "A1:F200", hasHeaders: false },
        provider_result: { os: [], ret: { rows: [["Plantéa", "September 2026"], ["Revenue", "", "Not publicly reported", "Awaiting input"]], rowCount: 2 } } } },
  ];
  const html = render({ id: "broker-saved-run", status: "waiting_for_action", plan: { name: "KPI dashboard" }, steps, result: {} });
  assert.match(html, /Report saved to Google Sheets — review needed/);
  assert.match(html, /Final review needs attention/);
  assert.match(html, /AURA has not verified the full requested outcome/);
  assert.match(html, />37<\/p>/);
  assert.match(html, /web page read/);
  assert.match(html, /Tools used/);
  assert.match(html, /Main output/);
  assert.ok(html.indexOf("Results from every tool") < html.indexOf("Tools used"));
  assert.ok(html.indexOf("Results from every tool") < html.indexOf('aria-label="Google Sheets result screen"'));
  assert.match(html, /Saved Google Sheets cells/);
  assert.match(html, /Cell A1/);
  assert.match(html, /Partial saved preview:/);
  assert.match(html, /Dashboard&#x27;!A1:F200/);
  assert.match(html, /Not publicly reported/);
  assert.match(html, /Awaiting input/);
  assert.match(html, /https:\/\/docs.google.com\/spreadsheets\/d\/final-workbook\/edit#gid=173&amp;range=A1%3AG37/);
  assert.doesNotMatch(html, /<iframe|Unsaved proposal|Workflow complete<\/|Schedule<\/button>/);
  assert.ok(html.indexOf('aria-label="Workflow summary"') < html.indexOf("Results from every tool"));
  assert.ok(html.indexOf("Results from every tool") < html.indexOf("Intermediate planning report"));
  assert.doesNotMatch(html, /Other tool outputs|What would you like to change/);
});

test("the existing 37-row Plantea snapshot restores the actual tables from activity when the cached result is empty", () => {
  const create = { step_key: "create", operation: "google-sheets.new-spreadsheet", provider_result: { ret: { spreadsheetId: "plantea-workbook", title: "Plantéa Skin KPI Dashboard" } }, outcome_check: { status: "verified" } };
  const steps = [
    { id: "create", key: "create", tool_slug: "google-sheets", status: "completed", output: create },
    { id: "save", key: "save", tool_slug: "google-sheets", operation: "google-sheets.update-multiple-rows", status: "completed", output: { resolved_arguments: { worksheetId: 173 }, provider_result: { ret: { spreadsheetId: "plantea-workbook", updatedRange: "Dashboard!A1:G37", updatedRows: 37 } } } },
    { id: "read", key: "read", tool_slug: "google-sheets", operation: "google-sheets.read-rows", status: "completed", output: { resolved_arguments: { spreadsheetId: "plantea-workbook", sheetName: "Dashboard", range: "A1:F200", hasHeaders: false }, provider_result: { ret: { rows: planteaRows } } } },
  ];
  const html = render({ id: "restored-plantea", status: "waiting_for_action", plan: { name: "Plantéa dashboard" }, steps, result: { outputs: [create] } });
  const doc = new JSDOM(html).window.document;
  const dropdown = doc.querySelector('[aria-label="Google Sheets result dropdown"]');
  const cells = dropdown.closest("article").querySelector('[aria-label="Saved Google Sheets cells"]');
  assert.equal(cells.querySelectorAll("tbody tr").length, 37);
  const visibleCells = [...cells.querySelectorAll("tbody td button")].map((cell) => cell.textContent.replaceAll("\u00a0", ""));
  assert.deepEqual(visibleCells, planteaRows.flat());
  assert.ok(doc.querySelector('[aria-label="Supporting workflow actions"]').contains(dropdown));
  assert.match(dropdown.closest("article").textContent, /Partial saved preview/);
  assert.doesNotMatch(html, /<iframe|What would you like to change/);
});

test("Results from every tool owns each tool dropdown and Tools used opens those same results", async () => {
  const dom = new JSDOM("<!doctype html><body><div id='app'></div></body>", { pretendToBeVisual: true, url: "https://aura.example.invalid" });
  const globals = { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    Element: dom.window.Element, SVGElement: dom.window.SVGElement, navigator: dom.window.navigator,
    requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window), cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true };
  const descriptors = Object.fromEntries(Object.keys(globals).map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  for (const [key, value] of Object.entries(globals)) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  let scrolled;
  dom.window.HTMLElement.prototype.scrollIntoView = function () { scrolled = this; };
  const { createRoot } = await import("react-dom/client");
  const app = document.getElementById("app"), root = createRoot(app);
  const click = async (element) => { assert.ok(element); await act(async () => element.click()); };
  const byLabel = (label) => app.querySelector(`[aria-label="${label}"]`);
  const byText = (text) => [...app.querySelectorAll("button")].find((button) => button.textContent === text);
  const saved = { ...run, id: "dropdown-run", steps: [
    { id: "web", key: "web", tool_slug: "web", status: "completed", output: { operation: "web.page.read", provider_result: { url: "https://example.com/serum", text: "Retrieved source" } } },
    { id: "report", key: "report", tool_slug: "aura", status: "completed", output: { operation: "report.compose", provider_result: { body: "Saved research report" } } },
    { id: "feedback", key: "feedback", tool_slug: "google-sheets", operation: "google-sheets.update-multiple-rows", status: "completed", output: {
      provider_result: { ret: { spreadsheetId: "exact-workbook", updatedRange: "Feedback!A1:B2" } },
      outcome_check: { status: "verified", observed: { range: "Feedback!A1:B2", values: [["Saved feedback table", "Review pricing"]] } },
    } },
    { id: "save", key: "save", tool_slug: "google-sheets", operation: "google-sheets.update-multiple-rows", status: "completed",
      output: { resolved_arguments: { worksheetId: 173 }, provider_result: { ret: { spreadsheetId: "exact-workbook", updatedRange: "Dashboard!A1:C2", updatedRows: 2 } },
        outcome_check: { status: "verified", observed: { range: "Dashboard!A1:C2", values: [["Company", "September 2026"], ["Revenue", "", "Not publicly reported"]] } } } },
    ...["earlier", "later"].map((period, index) => ({ id: period, key: period, tool_slug: "google-ads", operation: "google-ads.create-campaign-report", status: "completed", reason: `Read ${period} period`, output: {
      resolved_arguments: { accountId: "manager", customerClientId: "client", dateRange: "CUSTOM", startDate: `2026-0${index + 1}-01`, endDate: `2026-0${index + 1}-28` },
      provider_result: { ret: [{ campaign: { name: `${period} campaign` }, customer: { id: "client", currencyCode: "EUR", timeZone: "Europe/Berlin" }, metrics: { costMicros: String((index + 1) * 1000000) } }] },
    } })),
  ], result: {} };
  try {
    await act(async () => root.render(React.createElement(ResultsTestView, { run: saved })));
    const overview = byLabel("Supporting workflow actions"), main = byLabel("Google Sheets result dropdown");
    const summary = byLabel("Workflow summary");
    assert.equal(summary.parentElement.firstElementChild, summary, "the workflow summary must be first");
    assert.ok(overview.contains(main));
    assert.equal(overview.nextElementSibling, byLabel("Results by tool"));
    const toolLink = main.closest("article").querySelector("header a");
    assert.equal(main.open, false, "action history starts collapsed; the saved table is always visible above it");
    assert.match(byLabel("Saved Google Sheets cells").textContent, /Not publicly reported/);
    assert.equal(byLabel("Change result with a prompt"), null);
    const rangeTabs = byLabel("Saved sheet ranges");
    assert.equal(rangeTabs.querySelectorAll('[role="tab"]').length, 2);
    await click([...rangeTabs.querySelectorAll("button")].find((tab) => tab.textContent === "Feedback"));
    assert.match(byLabel("Saved Google Sheets cells").textContent, /Saved feedback table/);
    await click([...rangeTabs.querySelectorAll("button")].find((tab) => tab.textContent === "Dashboard"));
    assert.match(byLabel("Saved Google Sheets cells").textContent, /Not publicly reported/);
    assert.equal(toolLink.href, "https://docs.google.com/spreadsheets/d/exact-workbook/edit#gid=173&range=A1%3AC2");
    assert.equal(toolLink.target, "_blank");
    await click(byLabel("View Google Sheets results"));
    assert.equal(main.open, false);
    assert.match(byLabel("Saved Google Sheets cells").textContent, /Not publicly reported/);
    await click(toolLink);
    assert.equal(main.open, false, "native-tool link must not toggle its dropdown");
    const report = byLabel("ChatGPT result dropdown");
    assert.equal(report.open, true, "nonvisual saved content is immediately visible");
    await click(byLabel("View ChatGPT results"));
    assert.equal(report.open, true);
    assert.match(report.textContent, /Saved research report/);
    assert.ok(overview.contains(report));
    assert.equal(main.open, false);
    assert.equal(app.querySelector('[role="dialog"]'), null);
    await click(report.querySelector("summary"));
    await click(byLabel("View ChatGPT results"));
    assert.equal(report.open, true, "Tools used reopens a collapsed result");
    await click(byLabel("View Web research results"));
    const sources = byLabel("Web research result dropdown");
    assert.equal(sources.open, true);
    assert.equal(sources.closest("article").querySelector("header a").href, "https://example.com/serum");
    assert.ok(overview.contains(sources));
    await click(byText("View activity"));
    assert.match(byLabel("Inline tool result").querySelector("summary").textContent, /Workflow activity/);
    assert.equal(byLabel("Supporting workflow actions"), overview);
    assert.equal(app.querySelector('[role="dialog"]'), null);
    await click(byLabel("View Google Sheets results"));
    assert.equal(main.open, false);
    assert.equal(app.querySelectorAll('[aria-label="Google Sheets result screen"]').length, 1);
    await click(byLabel("View Google Ads results"));
    const ads = byLabel("Google Ads result screen");
    assert.equal(scrolled, ads.closest("article"));
    assert.ok(byLabel("Google Ads native view"));
    assert.equal(byLabel("Google Ads result dropdown").open, false, "tool navigation focuses the native view, not action history");
    assert.equal(byLabel("Google Ads saved snapshot").open, false);
    await click(byLabel("Google Ads saved snapshot").querySelector("summary"));
    assert.equal(byLabel("Google Ads saved snapshot").open, true);
    assert.match(ads.textContent, /earlier campaign/);
    assert.doesNotMatch(ads.textContent, /later campaign/);
    const select = ads.querySelector("select");
    await act(async () => { select.value = "later"; select.dispatchEvent(new dom.window.Event("change", { bubbles: true })); });
    assert.match(ads.textContent, /later campaign/);
    assert.doesNotMatch(ads.textContent, /earlier campaign/);
    await click([...ads.querySelectorAll('[role="tab"]')].find((button) => button.textContent === "Accounts & coverage"));
    assert.match(ads.textContent, /Europe\/Berlin/);
    assert.match(ads.textContent, /2026-01-01 – 2026-01-28/);
    assert.match(ads.textContent, /2026-02-01 – 2026-02-28/);
    await click([...ads.querySelectorAll('[role="tab"]')].find((button) => button.textContent === "Campaign data"));
    assert.match(ads.textContent, /later campaign/, "switching tabs preserves the selected saved report");

  } finally {
    await act(async () => root.unmount());
    dom.window.close();
    for (const [key, descriptor] of Object.entries(descriptors)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
  }
});


test("campaign mobile cards keep reporting notes out of platform metrics", () => {
  const step = { id: "read", key: "read", tool_slug: "google-sheets", operation: "google-sheets.read-rows", status: "completed", output: {
    operation: "google-sheets.read-rows", resolved_arguments: { spreadsheetId: "test-sheet", sheetName: "Summary", range: "A1:D4", hasHeaders: false },
    provider_result: { ret: { rows: [["Platform", "Currency", "Spend", "Clicks"], ["Google Ads", "EUR", "12.00", "10"], ["Meta Ads", "EUR", "Unavailable", "Unavailable"], ["Reporting scope", "Earlier history is unverified", "", ""]] } },
  } };
  const doc = new JSDOM(render({ ...run, steps: [step], result: {} })).window.document;
  const cards = doc.querySelector('[aria-label="Campaign report cards"]');
  assert.equal(cards.querySelectorAll("article").length, 2);
  assert.match(cards.textContent, /Metrics unavailable/);
  assert.match(cards.querySelector(":scope > details").textContent, /Earlier history is unverified/);
  assert.match(doc.querySelector('a[href="/results/collect"]').textContent, /Collect saved results/);
});

test("advertising inputs prioritize native tools and keep AURA snapshots secondary", () => {
  const receipt = (key, tool, operation, provider_result, resolved_arguments = {}) => ({ id: key, key, tool_slug: tool, operation, status: "completed",
    output: { operation, provider_result, resolved_arguments, critic: { action: "accept" }, outcome_check: { status: "verified" } } });
  const steps = [
    receipt("ads", "google-ads", "google-ads.create-campaign-report", { ret: { results: [{ campaign: { name: "Search campaign" }, metrics: { costMicros: "12000000", impressions: "100", clicks: "0" } }] } }, { accountId: "manager", customerClientId: "client" }),
    receipt("meta", "meta-ads-direct", "meta-ads.insights.read", { account_id: "act-test", data: [], date_range: { since: "2026-01-01", until: "2026-06-30" } }),
  ];
  const doc = new JSDOM(render({ ...run, steps, result: {} })).window.document;
  for (const tool of ["Google Ads", "Meta Ads"]) {
    const screen = doc.querySelector(`[aria-label="${tool} result screen"]`);
    assert.ok(screen, tool);
    assert.equal(screen.closest("details").getAttribute("aria-label"), `${tool} saved snapshot`);
    assert.equal(screen.closest("details").open, false, "AURA reconstruction is not the default tool view");
    const native = doc.querySelector(`[aria-label="${tool} native view"]`);
    assert.equal(native.closest("details"), null);
    assert.equal(native.querySelector("a").target, "_blank");
    assert.match(native.textContent, /new tab/);
    assert.equal(native.querySelector("iframe"), null, "private ads managers are not forced into blocked iframes");
    assert.match(screen.textContent, /Used as input/);
    assert.match(screen.textContent, /Saved source data in AURA/);
    assert.equal(screen.querySelectorAll('[role="tab"]').length, 2);
    assert.doesNotMatch(screen.textContent, /\bret\b|spreadsheetId|Empty list returned/);
  }
  const google = doc.querySelector('[aria-label="Google Ads result screen"]');
  assert.match(google.textContent, /Search campaign/);
  assert.match(google.textContent, /Account: client/);
  assert.doesNotMatch(google.textContent, /Account: manager/);
  const meta = doc.querySelector('[aria-label="Meta Ads result screen"]');
  assert.match(meta.textContent, /Metrics are unavailable, not zero/);
  assert.match(meta.textContent, /2026-01-01 – 2026-06-30/);
});

test("Canva stays the main output with a native design link and a collapsed snapshot", () => {
  const link = "https://www.canva.com/api/design/test-signed-token/edit";
  const step = { id: "design", key: "design", tool_slug: "canva", status: "completed", output: {
    operation: "canva.design.get", provider_result: { design: { id: "DA-TEST", title: "Campaign review", page_count: 1,
      urls: { edit_url: link }, thumbnail: { url: "https://media.canva.com/test-thumbnail" } } },
    critic: { action: "accept" }, outcome_check: { status: "verified" },
  } };
  const doc = new JSDOM(render({ ...run, steps: [step], result: {} })).window.document;
  const native = doc.querySelector('[aria-label="Canva native view"]');
  assert.ok(native);
  assert.equal(native.querySelector("a").href, link);
  assert.equal(native.querySelector("a").target, "_blank");
  assert.equal(native.querySelector("iframe"), null, "private editor links are not converted to public embeds");
  assert.match(native.closest("article").querySelector("header").textContent, /Main output/);
  const snapshot = doc.querySelector('[aria-label="Canva saved snapshot"]');
  assert.equal(snapshot.open, false);
  assert.ok(snapshot.querySelector("img"), "saved thumbnail remains reachable as a snapshot");
});
