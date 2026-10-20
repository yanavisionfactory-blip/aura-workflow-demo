import test from "node:test";
import assert from "node:assert/strict";
import { campaignReportGroups } from "../src/lib/campaignReport.mjs";

const headings = ["Campaign brief", "Google Search drafts", "Facebook and Instagram drafts",
  "Google Business Profile draft", "Indoor screen draft", "Asset checklist", "Approval tracker and implementation handoff"];
const body = headings.map((title) => `## ${title}\n${"Complete saved source and draft copy. ".repeat(4)}`).join("\n\n");

test("complete native campaign reports expose all saved sections without altering content", () => {
  const parsed = campaignReportGroups("**Draft for review**\n\n" + body);
  assert.equal(parsed.intro, "**Draft for review**");
  assert.deepEqual(parsed.groups.map((group) => group.name), ["Brief", "Google Ads", "Social ads",
    "Business Profile", "Indoor screens", "Assets", "Approvals and handoff"]);
  assert.equal(parsed.groups.flatMap((group) => group.sections).length, headings.length);
  assert.ok(parsed.groups.every((group) => group.sections[0].body.includes("Complete saved source and draft copy.")));
});

test("missing channels and ordinary reports do not become completed campaign packages", () => {
  assert.equal(campaignReportGroups("## Executive summary\nOrdinary review."), null);
  assert.equal(campaignReportGroups(body.replace(/## Indoor screen draft[\s\S]*?(?=## Asset)/, "")), null);
  assert.equal(campaignReportGroups(null), null);
});

test("channel asset requirements stay separate from channel draft copy", () => {
  const parsed = campaignReportGroups(body + "\n\n## Instagram asset requirements\n" + "Rights approval is pending. ".repeat(4));
  assert.equal(parsed.groups.find((group) => group.name === "Assets").sections.length, 2);
  assert.equal(parsed.groups.find((group) => group.name === "Social ads").sections.length, 1);
});
