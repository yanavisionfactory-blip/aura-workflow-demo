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

test("ordinary reports and missing core review sections retain the generic renderer", () => {
  assert.equal(campaignReportGroups("## Executive summary\nOrdinary review."), null);
  assert.equal(campaignReportGroups(body.replace(/## Asset checklist[\s\S]*?(?=## Approval)/, "")), null);
  assert.equal(campaignReportGroups(null), null);
});

test("local booking packages expose their actual channels without inventing Search or screens", () => {
  const titles = ["Campaign brief", "Google Business Profile posts", "Meta ad variations",
    "15-second Reel storyboard", "Vagaro booking destination and source checks", "Asset checklist", "Approval table", "Implementation handoff"];
  const sections = titles.map((title, index) => `## ${title}\nSaved content ${index}. ${"Draft for client review. ".repeat(4)}`);
  const parsed = campaignReportGroups(sections.join("\n\n"));
  assert.deepEqual(parsed.groups.map((group) => group.name), ["Brief", "Social ads", "Business Profile", "Reel",
    "Booking and source checks", "Assets", "Approvals and handoff"]);
  assert.deepEqual(parsed.groups.flatMap((group) => group.sections).map((section) => section.body).sort(), sections.map((section) => section.trim()).sort());
  assert.equal(parsed.groups.find((group) => group.name === "Approvals and handoff").sections.length, 2);
});

test("channel asset requirements stay separate from channel draft copy", () => {
  const parsed = campaignReportGroups(body + "\n\n## Instagram asset requirements\n" + "Rights approval is pending. ".repeat(4));
  assert.equal(parsed.groups.find((group) => group.name === "Assets").sections.length, 2);
  assert.equal(parsed.groups.find((group) => group.name === "Social ads").sections.length, 1);
});

test("top-level campaign sections keep their subheadings in the correct channel", () => {
  const parsed = campaignReportGroups(headings.map((title) => `# ${title}\n## Detail for this section\n${"Saved complete draft. ".repeat(5)}`).join("\n\n"));
  assert.equal(parsed.groups.length, 7);
  assert.equal(parsed.groups.find((group) => group.name === "Indoor screens").sections[0].title, "Indoor screen draft");
  assert.ok(parsed.groups.every((group) => group.sections[0].body.includes("## Detail for this section")));
  const titled = campaignReportGroups("# Campaign package\n\n" + body);
  assert.equal(titled.groups.length, 7);
  assert.equal(titled.intro, "# Campaign package");
});
