import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  meaningfulMetrics,
  primaryResultFromOutputs,
  readableResultText,
  resultMetrics,
  selectPrimaryOutcome,
  supportingReceipts,
  visualResultChoices,
} from "../src/lib/resultPresentation.mjs";

test("multiple Canva designs and completed exports stay reachable beside the main creative", () => {
  const activity = [
    { status: "completed", stepKey: "square", tool: "Canva", output: { operation: "canva.import.get", provider_result: {
      job: { status: "success", result: { designs: [{ id: "square", title: "Square creative", urls: { edit_url: "https://www.canva.com/design/square/edit" } }] } } } } },
    { status: "completed", stepKey: "square_export", tool: "Canva", output: { operation: "canva.export.get", provider_result: {
      job: { id: "square-export", status: "success", urls: ["https://export-download.canva.com/square.png"] } } } },
    { status: "completed", stepKey: "main_export", tool: "Canva", output: { operation: "canva.export.get", provider_result: {
      job: { id: "main-export", status: "success", urls: ["https://export-download.canva.com/main.png"] } } } },
    { status: "completed", stepKey: "pending_export", tool: "Canva", output: { operation: "canva.export.get", provider_result: {
      job: { id: "pending-export", status: "in_progress", urls: ["https://export-download.canva.com/not-finished.png"] } } } },
  ];
  const receipts = supportingReceipts({}, activity, { provider: "Canva", link: "https://www.canva.com/design/main/edit",
    downloadUrl: "https://export-download.canva.com/main.png" }, { supporting_step_keys: [] });
  assert.deepEqual(receipts.map((item) => item.link), ["https://www.canva.com/design/square/edit", "https://export-download.canva.com/square.png"]);
  assert.equal(receipts[0].title, "Square creative");
});

test("read-only campaign verification shows the real reused creative without claiming creation", () => {
  const outputs = ["square", "landscape"].map((id) => ({ step_key: id, operation: "canva.design.get", provider_result: {
    design: { id, title: id + " creative", urls: { edit_url: `https://www.canva.com/design/${id}/edit` },
      thumbnail: { url: `https://media.canva.com/${id}.png` } } } }));
  const primary = primaryResultFromOutputs(outputs, { title: "Campaign package verified" }, { primary_step_key: "landscape", artifact_step_key: "landscape" });
  assert.equal(primary.kind, "presentation");
  assert.equal(primary.designId, "landscape");
  assert.equal(primary.providerVerb, "Reused from");
  assert.equal(primary.thumbnailUrl, "https://media.canva.com/landscape.png");
  assert.doesNotMatch(primary.completionSummary, /created|sent|published/i);
  const activity = outputs.map((output) => ({ status: "completed", stepKey: output.step_key, tool: "Canva", output }));
  assert.deepEqual(resultMetrics([], activity), [{ value: "2", label: "existing creatives reviewed" }]);
  assert.equal(supportingReceipts({}, activity, primary, { supporting_step_keys: [] }).length, 1);
  const choices = visualResultChoices(activity);
  assert.deepEqual(choices.map((choice) => choice.key), ["square", "landscape"]);
  assert.equal(choices[1].result.designId, "landscape");
  assert.equal(visualResultChoices(activity.map((step) => ({ ...step, status: "failed" }))).length, 0);
});

test("saved WordPress articles use verified returned bodies instead of old planned content", () => {
  const output = { operation: "wordpress-org.update-post", critic: { action: "accept" }, outcome_check: { status: "verified" },
    resolved_arguments: { post: "108", content: "old preparation note" }, provider_result: { ret: {
      id: 108, status: "draft", title: { raw: "Plano guide" }, content: { raw: "<p>Complete saved article.</p>" } } } };
  const result = primaryResultFromOutputs([output], { deliverable: JSON.stringify([{ operation: "wordpress-org.update-post", arguments: {} }]) });
  assert.equal(result.kind, "articles");
  assert.equal(result.articles[0].body, "Complete saved article.");
  assert.equal(result.articles[0].words, 3);
  assert.doesNotMatch(JSON.stringify(result), /preparation|arguments/);
  assert.notEqual(primaryResultFromOutputs([{ ...output, outcome_check: { status: "pending" } }]).kind, "articles");
});

test("read-only WordPress reviews show actual full drafts and never claim new saves", () => {
  const output = { operation: "wordpress-org.search-posts", resolved_arguments: { search: "Guide", statuses: ["draft"] },
    outcome_check: { status: "verified" }, critic: { action: "accept" }, provider_result: { ret: [
      { id: 1, status: "draft", title: { raw: "Dallas guide" }, content: { raw: "<p>Full existing article.</p>" } },
      { id: 2, status: "publish", title: { raw: "Published guide" }, content: { raw: "<p>Published content.</p>" } },
    ] } };
  const result = primaryResultFromOutputs([output, output]);
  assert.equal(result.kind, "articles");
  assert.equal(result.articles.length, 1);
  assert.equal(result.articles[0].body, "Full existing article.");
  assert.equal(result.articles[0].reused, true);
  assert.match(result.completionSummary, /Saved content reused/);
  assert.doesNotMatch(result.completionTitle, /saved/i);
  assert.deepEqual(resultMetrics([], [{ status: "completed", output }]), [{ value: "1", label: "existing draft articles reviewed" }]);
  assert.notEqual(primaryResultFromOutputs([{ ...output, outcome_check: { status: "pending" } }]).kind, "articles");
  assert.notEqual(primaryResultFromOutputs([{ ...output, resolved_arguments: { statuses: ["publish"] } }]).kind, "articles");
  const handoff = { step_key: "handoff", operation: "jira.issue.get", provider_result: { result_url: "https://example.atlassian.net/browse/DEMO-1" } };
  const withHandoff = primaryResultFromOutputs([output, handoff], {}, { primary_step_key: "handoff" });
  assert.equal(withHandoff.kind, "articles");
  assert.equal(withHandoff.articles[0].body, "Full existing article.");
  assert.notEqual(primaryResultFromOutputs([handoff], {}, { primary_step_key: "handoff" }).kind, "articles");
});

test("workflow transport is not rendered as a deliverable", () => {
  assert.equal(readableResultText('[{"operation":"wordpress-org.search-posts","arguments":{"search":"108"}}]'), "Review the saved app results below.");
  assert.equal(readableResultText("Saved drafts are ready for review."), "Saved drafts are ready for review.");
  assert.equal(readableResultText('[{"keyword":"AC repair Dallas","volume":20}]'), '[{"keyword":"AC repair Dallas","volume":20}]');
});

test("an existing Jira task update is labelled as an update", () => {
  const result = primaryResultFromOutputs([{ operation: "jira.issue.update", provider_result: {
    result_url: "https://example.atlassian.net/browse/DEMO-1" } }]);
  assert.equal(result.providerVerb, "Updated in");
  const readback = primaryResultFromOutputs([{ operation: "jira.issue.get", provider_result: {
    result_url: "https://example.atlassian.net/browse/DEMO-1" } }]);
  assert.equal(readback.providerVerb, "Checked in");
});

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

test("a confirmed Canva import displays its real thumbnail and editor link", () => {
  const primary = primaryResultFromOutputs([{ operation: "canva.presentation.create", provider_result: {
    job: { result: { designs: [{ id: "design-123", thumbnail: { url: "https://document-export.canva.com/thumbnail/slide.png?token=abc" }, urls: { edit_url: "https://www.canva.com/api/design/opaque/edit" } }] } },
  } }], { title: "Pilot brief" });
  assert.equal(primary.thumbnailUrl, "https://document-export.canva.com/thumbnail/slide.png?token=abc");
  assert.equal(primary.link, "https://www.canva.com/api/design/opaque/edit");
  const unsafe = primaryResultFromOutputs([{ operation: "canva.presentation.create", provider_result: {
    designs: [{ id: "design-123", thumbnail: { url: "https://outside.example/track?token=abc" } }],
  } }], { title: "Pilot brief" });
  assert.equal(unsafe.thumbnailUrl, null);
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

test("a finished Canva presentation is the visual result and email delivery remains secondary", () => {
  const delivery = { kind: "email", provider: "Gmail", subject: "Your story", link: "https://mail.google.com/mail/u/0/#sent/message-1", artifactDelivered: true,
    artifact: { kind: "presentation", title: "The fairy tale", provider: "Canva", link: "https://www.canva.com/design/design-123/edit" } };
  const primary = selectPrimaryOutcome({ primaryResult: delivery });
  assert.equal(primary.kind, "presentation");
  assert.equal(primary.title, "The fairy tale");
  assert.equal(primary.delivery, delivery);
  const receipts = supportingReceipts({}, [
    { status: "completed", stepKey: "design", tool: "Canva", action: "Create the story", output: { operation: "canva.presentation.create", provider_result: { designs: [{ id: "design-123" }] } } },
    { status: "completed", stepKey: "send", tool: "Gmail", action: "Send the presentation", liveOutput: "Completed", output: { operation: "gmail.send", provider_result: { result_url: delivery.link } } },
  ], primary, { supporting_step_keys: ["design"] });
  assert.equal(receipts.length, 1);
  assert.equal(receipts[0].tool, "Gmail");
  assert.equal(receipts[0].title, "Send the presentation");
  assert.equal(receipts[0].link, delivery.link);
});

test("finished Canva work shows the exact resolved slide text and receipt-backed metrics", () => {
  const activity = [{ status: "completed", output: {
    step_key: "audiences", operation: "mailchimp.audiences.list",
    provider_result: { lists: [{ name: "Pilot audience", stats: { member_count: 184 } }] },
  } }, { status: "completed", output: {
    step_key: "pilot_slide", operation: "canva.presentation.create",
    resolved_arguments: { title: "Pilot brief", layout: "slides", phases: [{ period: "Pilot", title: "Audience overview", items: ["Audience: Pilot audience", "Contacts: 184"] }] },
    provider_result: { page_count: 1, designs: [{ id: "a1b2c3" }] },
  } }];
  const primary = primaryResultFromOutputs(activity.map((step) => step.output), { title: "Mailchimp audience pilot brief", deliverable: "Design ID: a1b2c3\nEdit URL: https://www.canva.com/design/a1b2c3/edit" }, { primary_step_key: "pilot_slide" });
  assert.equal(primary.title, "Pilot brief");
  assert.deepEqual(primary.preview.slides[0].items, ["Audience: Pilot audience", "Contacts: 184"]);
  assert.deepEqual(resultMetrics([], activity), [
    { value: "1", label: "slide created" }, { value: "1", label: "audience used" }, { value: "184", label: "contacts in audience" },
  ]);
  assert.deepEqual(resultMetrics([], activity.slice(0, 1)), [
    { value: "1", label: "audience used" }, { value: "184", label: "contacts in audience" },
  ]);
});

test("a draft template and incomplete provider calls cannot create a fake visual or metrics", () => {
  const primary = primaryResultFromOutputs([{ operation: "canva.presentation.create",
    resolved_arguments: { title: "Draft", phases: [{ period: "Pilot", title: "Overview", items: ["Contacts: {{steps.audiences.lists[0].stats.member_count}}"] }] },
    provider_result: { designs: [{ id: "a1b2c3" }] },
  }], { title: "Draft" });
  assert.equal(primary.preview, null);
  assert.deepEqual(resultMetrics([], [{ status: "failed", output: { operation: "canva.presentation.create", provider_result: { designs: [{ id: "a1b2c3" }] } } }]), []);
});

test("Mailchimp supporting result shows real audience details and opens its account", () => {
  const receipts = supportingReceipts({}, [{ stepKey: "audiences", tool: "Mailchimp", action: "Read audiences", status: "completed", output: {
    operation: "mailchimp.audiences.list",
    provider_result: { lists: [{ name: "Pilot audience", web_id: 443, stats: { member_count: 184 }, _links: [{ rel: "self", href: "https://us19.api.mailchimp.com/3.0/lists/list-id" }] }] },
  } }], { provider: "Canva" }, { supporting_step_keys: ["audiences"] });
  assert.deepEqual(receipts[0].preview, [{ name: "Pilot audience", contacts: 184 }]);
  assert.equal(receipts[0].link, "https://us19.admin.mailchimp.com/lists/members/?id=443");
});

test("created Google Docs display their completed body and link to the original", () => {
  const result = primaryResultFromOutputs([{ operation: "docs.create", resolved_arguments: { title: "A short story", body: "Once upon a time…" }, provider_result: { id: "doc-123", name: "A short story" } }], { title: "Story" });
  assert.equal(result.kind, "document");
  assert.equal(result.preview.body, "Once upon a time…");
  assert.equal(result.link, "https://docs.google.com/document/d/doc-123/edit");
});

test("Pipedream Google Docs creation shows the exact completed briefing and link", () => {
  const output = {
    step_key: "draft", operation: "google-docs.create-document", tool: "google-docs",
    resolved_arguments: { title: "Monday Briefing Draft", content: "Calendar and eight source notes." },
    provider_result: { ret: { documentId: "149UIO7QH2jBEgsZmSGUc3NIrWP6dEJ0BY2zZPBIiSFw", title: "Monday Briefing Draft",
      url: "https://docs.google.com/document/d/149UIO7QH2jBEgsZmSGUc3NIrWP6dEJ0BY2zZPBIiSFw/edit" } },
  };
  const result = primaryResultFromOutputs([output], { title: "Monday calendar + EB2 NIW notes to Google Doc briefing", deliverable: "Old plan text" }, { primary_step_key: "draft" });
  assert.equal(result.kind, "document");
  assert.equal(result.preview.title, "Monday Briefing Draft");
  assert.equal(result.preview.body, "Calendar and eight source notes.");
  assert.equal(result.provider, "Google Docs");
  assert.equal(result.link, "https://docs.google.com/document/d/149UIO7QH2jBEgsZmSGUc3NIrWP6dEJ0BY2zZPBIiSFw/edit");
});

test("completed backend runs consume resolved presentation metrics", () => {
  const source = readFileSync(new URL("../src/pages/Demo.jsx", import.meta.url), "utf8");
  assert.equal(source.includes("run.result?.result_presentation"), true);
  assert.equal(source.includes("metrics: resultPresentation?.metrics || []"), true);
  assert.equal(source.includes("label: completedCount === 1"), false);
});
