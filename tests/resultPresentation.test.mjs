import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  meaningfulMetrics,
  primaryResultFromOutputs,
  selectPrimaryOutcome,
  supportingReceipts,
} from "../src/lib/resultPresentation.mjs";

test("process counters do not masquerade as meaningful result metrics", () => {
  assert.deepEqual(meaningfulMetrics([
    { value: "4", label: "steps completed" },
    { value: "18°C", label: "afternoon temperature" },
  ]), [{ value: "18°C", label: "afternoon temperature" }]);
});

test("a Canva deliverable remains primary when Gmail runs afterward", () => {
  const primary = primaryResultFromOutputs([
    {
      tool: "canva",
      operation: "canva.presentation.create",
      provider_result: { job: { result: { designs: [{ id: "design-123" }] } } },
    },
    {
      tool: "google",
      operation: "gmail.send",
      provider_result: { result_url: "https://mail.google.com/mail/u/0/#sent/message-1" },
    },
  ], {
    title: "Munich weather presentation",
    deliverable: "A populated presentation using tomorrow's forecast.",
  });

  assert.equal(primary.provider, "Canva");
  assert.equal(primary.link, "https://www.canva.com/design/design-123/edit");
  assert.equal(primary.linkLabel, "Open in Canva");
});

test("verified Canva export URLs become the download action", () => {
  const primary = primaryResultFromOutputs([
    {
      operation: "canva.presentation.create",
      provider_result: { job: { result: { designs: [{ id: "design-123" }] } } },
    },
    {
      operation: "canva.export.create",
      provider_result: { job: { urls: ["https://export-download.canva.com/weather.pdf"] } },
    },
  ], { title: "Weather deck" });
  assert.equal(primary.downloadUrl, "https://export-download.canva.com/weather.pdf");
});

test("result-title relevance can make an action outcome primary", () => {
  const primary = selectPrimaryOutcome({
    title: "Jira tasks created",
    outcomes: [
      { type: "document", title: "Action items extracted from Notion" },
      { type: "crm", title: "Jira tasks created", items: [{ label: "PROJ-1" }] },
    ],
  });
  assert.equal(primary.title, "Jira tasks created");
});

test("artifact-producing tool links outrank earlier read receipts", () => {
  const primary = primaryResultFromOutputs([
    { tool: "notion", operation: "notion.page.read", provider_result: { result_url: "https://notion.so/source" } },
    { tool: "jira", operation: "jira.issue.create", provider_result: { result_url: "https://example.atlassian.net/browse/PROJ-1" } },
  ], { title: "Jira tasks created" });
  assert.equal(primary.provider, "Jira");
  assert.equal(primary.link, "https://example.atlassian.net/browse/PROJ-1");
});

test("shared Google execution identifies a Gmail result precisely", () => {
  const primary = primaryResultFromOutputs([
    { tool: "google", operation: "gmail.send", provider_result: { result_url: "https://mail.google.com/mail/u/0/#sent/message-1" } },
  ], { title: "Email sent" });
  assert.equal(primary.provider, "Gmail");
  assert.equal(primary.linkLabel, "Open in Gmail");
});

test("provider aliases keep supporting receipts from repeating the primary result", () => {
  const results = {
    title: "Campaign breakdown created",
    outcomes: [{
      type: "document",
      title: "Campaign breakdown",
      link: "https://docs.google.com/spreadsheets/d/1/edit",
      linkLabel: "Open in Sheets",
    }],
  };
  const primary = selectPrimaryOutcome(results);
  const receipts = supportingReceipts(results, [
    { tool: "Google Sheets", action: "Create campaign breakdown", status: "completed" },
    { tool: "Meta Ads", action: "Read campaign results", status: "completed" },
  ], primary);
  assert.deepEqual(receipts.map((receipt) => receipt.tool), ["Meta Ads"]);
});

test("supporting receipts omit the primary tool and unfinished steps", () => {
  const receipts = supportingReceipts({}, [
    { tool: "AURA Intelligence", action: "Check Munich weather", status: "completed", liveOutput: "→ Forecast retrieved" },
    { tool: "Canva", action: "Create presentation", status: "completed", liveOutput: "→ Presentation created" },
    { tool: "Gmail", action: "Email presentation", status: "completed", liveOutput: "→ Email delivered" },
    { tool: "Slack", action: "Post a message", status: "failed" },
  ], { provider: "Canva" });
  assert.deepEqual(receipts.map((receipt) => receipt.tool), ["AURA Intelligence", "Gmail"]);
  assert.deepEqual(receipts.map((receipt) => receipt.title), ["Forecast retrieved", "Email delivered"]);
});

test("the results UI has one deliverable and one run-details disclosure", () => {
  const source = readFileSync(new URL("../src/components/aura/ResultsView.jsx", import.meta.url), "utf8");
  assert.equal(source.includes("Your result"), true);
  assert.equal(source.includes(">Preview</p>"), true);
  assert.equal(source.includes("Also completed"), true);
  assert.equal(source.includes("View run details"), true);
  assert.equal(source.includes("outcome.items.map"), true);
  assert.equal(source.match(/Suggested next/g)?.length, 1);
  assert.equal(source.includes("Tools used"), false);
  assert.equal(source.includes("What happened"), false);
  assert.equal(source.includes("Still tracking"), false);
});
