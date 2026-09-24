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

test("email delivery becomes primary while preserving the attached Canva result", () => {
  const primary = primaryResultFromOutputs([
    {
      tool: "canva",
      operation: "canva.presentation.create",
      provider_result: { job: { result: { designs: [{ id: "design-123" }] } } },
    },
    {
      tool: "google",
      operation: "gmail.send",
      provider_result: {
        result_url: "https://mail.google.com/mail/u/0/#sent/message-1",
        recipient: "yana@example.com",
        subject: "Munich weather forecast",
        attachments: [{ filename: "munich-weather.pdf" }],
      },
    },
  ], {
    title: "Munich weather presentation",
    deliverable: "A populated presentation using tomorrow's forecast.",
  });

  assert.equal(primary.provider, "Gmail");
  assert.equal(primary.providerVerb, "Sent with");
  assert.equal(primary.link, "https://mail.google.com/mail/u/0/#sent/message-1");
  assert.equal(primary.linkLabel, "Open in Gmail");
  assert.equal(primary.recipient, "yana@example.com");
  assert.equal(primary.artifact.provider, "Canva");
  assert.equal(primary.artifact.link, "https://www.canva.com/design/design-123/edit");
  assert.equal(primary.artifact.linkLabel, "View presentation");
  assert.equal(primary.artifactDelivered, true);
  assert.match(primary.completionSummary, /presentation attached/);
});

test("a created presentation does not imply an email attachment was delivered", () => {
  const primary = primaryResultFromOutputs([
    { operation: "canva.presentation.create", provider_result: { designs: [{ id: "design-123" }] } },
    { operation: "gmail.send", provider_result: { recipient: "yana@example.com" }, resolved_arguments: { attachments: [{ filename: "requested.pdf" }] } },
  ], { title: "Story" });
  assert.equal(primary.artifactDelivered, false);
  assert.equal(primary.completionSummary, "Delivered through Gmail to yana@example.com.");
});

test("a Canva presentation remains primary when it is not delivered elsewhere", () => {
  const primary = primaryResultFromOutputs([{
    tool: "canva",
    operation: "canva.presentation.create",
    provider_result: { job: { result: { designs: [{ id: "design-123" }] } } },
  }], { title: "Munich weather presentation" });

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

test("compiled result contract overrides provider-order guessing", () => {
  const primary = primaryResultFromOutputs([
    {
      step_key: "create_tasks",
      tool: "jira",
      operation: "jira.issue.create",
      provider_result: { result_url: "https://example.atlassian.net/browse/PROJ-1" },
    },
    {
      step_key: "send_notice",
      tool: "google",
      operation: "gmail.send",
      provider_result: { result_url: "https://mail.google.com/mail/u/0/#sent/message-1" },
    },
  ], { title: "Jira tasks created" }, {
    primary_step_key: "create_tasks",
  });

  assert.equal(primary.provider, "Jira");
  assert.equal(primary.link, "https://example.atlassian.net/browse/PROJ-1");
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

test("supporting receipts omit the final delivery tool and retain creation receipts", () => {
  const receipts = supportingReceipts({}, [
    { tool: "AURA Intelligence", action: "Check Munich weather", status: "completed", liveOutput: "→ Forecast retrieved" },
    {
      tool: "Canva",
      action: "Create presentation",
      status: "completed",
      liveOutput: "→ Presentation created",
      output: {
        operation: "canva.presentation.create",
        provider_result: { job: { result: { designs: [{ id: "design-123" }] } } },
      },
    },
    { tool: "Gmail", action: "Email presentation", status: "completed", liveOutput: "→ Email delivered" },
    { tool: "Slack", action: "Post a message", status: "failed" },
  ], { provider: "Gmail" });
  assert.deepEqual(receipts.map((receipt) => receipt.tool), ["AURA Intelligence", "Canva"]);
  assert.deepEqual(receipts.map((receipt) => receipt.title), ["Forecast retrieved", "Presentation created"]);
  assert.equal(receipts[0].link, null);
  assert.equal(receipts[1].link, "https://www.canva.com/design/design-123/edit");
  assert.equal(receipts[1].linkLabel, "View in Canva");
});

test("compiled supporting step selection hides transport-only receipts", () => {
  const receipts = supportingReceipts({}, [
    { stepKey: "weather", tool: "AURA", action: "Read weather", status: "completed" },
    { stepKey: "export", tool: "Canva", action: "Export PDF", status: "completed" },
    { stepKey: "send", tool: "Gmail", action: "Send email", status: "completed" },
  ], { provider: "Gmail" }, {
    supporting_step_keys: ["weather"],
  });

  assert.deepEqual(receipts.map((receipt) => receipt.title), ["Read weather"]);
});

test("an explicit empty supporting contract does not recreate fallback receipts", () => {
  const receipts = supportingReceipts({
    outcomes: [{ title: "Fallback outcome", detail: "Legacy fallback" }],
  }, [
    { stepKey: "send", tool: "Gmail", action: "Send email", status: "completed" },
  ], { provider: "Gmail" }, {
    supporting_step_keys: [],
  });

  assert.deepEqual(receipts, []);
});

test("the results UI uses supporting app receipts without duplicate run details", () => {
  const source = readFileSync(new URL("../src/components/aura/ResultsView.jsx", import.meta.url), "utf8");
  assert.equal(source.includes("Your result"), true);
  assert.equal(source.includes(">Summary</p>"), true);
  assert.equal(source.includes("Sent email"), true);
  assert.equal(source.includes("View presentation"), true);
  assert.equal(source.includes("Attached and delivered"), true);
  assert.equal(source.includes("!isFailure && !backendRunId"), true);
  assert.equal(source.includes("Also completed"), true);
  assert.equal(source.includes("View run details"), false);
  assert.equal(source.includes("Workflow activity"), false);
  assert.equal(source.includes("Output receipts"), false);
  assert.equal(source.includes("View in ${receipt.tool}"), true);
  assert.equal(source.match(/Suggested next/g)?.length, 1);
  assert.equal(source.includes("Tools used"), false);
  assert.equal(source.includes("What happened"), false);
  assert.equal(source.includes("Still tracking"), false);
});

test("completed backend runs consume resolved presentation metrics", () => {
  const source = readFileSync(new URL("../src/pages/Demo.jsx", import.meta.url), "utf8");
  assert.equal(source.includes("run.result?.result_presentation"), true);
  assert.equal(source.includes("metrics: resultPresentation?.metrics || []"), true);
  assert.equal(source.includes("label: completedCount === 1"), false);
});
