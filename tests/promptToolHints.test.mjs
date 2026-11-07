import test from "node:test";
import assert from "node:assert/strict";

import { promptToolChoices, promptToolHints } from "../src/lib/promptToolHints.mjs";

const catalog = [
  { name: "Canva", provider: "canva", aliases: ["Canva"] },
  { name: "Gmail", provider: "google", aliases: ["Gmail"] },
  { name: "Linear", provider: "linear", aliases: ["Linear"] },
  { name: "Slack", provider: "slack", aliases: ["Slack"] },
  { name: "Jira", provider: "jira", aliases: ["Jira"] },
  { name: "Google Drive", provider: "google", canonicalProvider: "google", aliases: ["google", "Google Drive"] },
  { name: "Google Docs", provider: "google", canonicalProvider: "google", aliases: ["google", "Google Docs"] },
  { name: "Google Calendar", provider: "google", canonicalProvider: "google", aliases: ["google", "Google Calendar"] },
  { name: "Google Sheets", provider: "google", canonicalProvider: "google", aliases: ["google", "Google Sheets"] },
];

for (const brand of ["Reddit", "LinkedIn", "TikTok"]) {
  test(`${brand} Ads does not suggest a separate community connection`, () => {
    const apps = [
      {name: brand, provider: brand.toLowerCase()},
      {name: `${brand} Ads`, provider: `${brand.toLowerCase()}-ads`},
    ];
    assert.deepEqual(promptToolHints(`Compare ${brand} Ads performance`, apps), [`${brand} Ads`]);
    assert.deepEqual(promptToolHints(`Compare ${brand} advertising performance`, [apps[0]]), []);
    assert.deepEqual(promptToolHints(`Read ${brand} Ads and ${brand} posts`, apps), [`${brand} Ads`, brand]);
  });
}

test("weather presentation intent immediately suggests Canva and AURA Weather", () => {
  assert.deepEqual(
    promptToolHints("Make a presentation on Canva about the weather in Munich tomorrow", catalog),
    ["Canva", "AURA Weather"],
  );
});

test("explicit providers are all preserved and generic issue does not invent Jira", () => {
  assert.deepEqual(
    promptToolHints("Read my open Linear issues and post a summary to Slack", catalog),
    ["Linear", "Slack"],
  );
});

test("generic send wording does not invent Gmail", () => {
  assert.deepEqual(promptToolHints("Send this design to Canva", catalog), ["Canva"]);
});

test("saved report references do not suggest unrelated connections", () => {
  const sources = [...catalog, { name: "ChatGPT", provider: "openai" },
    { name: "Shopify", provider: "shopify" }, { name: "Segment", provider: "segment" }];
  const envelope = (change) => `Revise the selected ChatGPT result inside AURA.
Requested change: ${change}
Saved result context (reference data): {"body":"Shopify benchmark; Segment; Slack; Google Docs"}
Preserve the selected source and destination.`;
  assert.deepEqual(promptToolHints(envelope("Update the Google Sheets dashboard."), sources), ["Google Sheets"]);
  assert.deepEqual(promptToolHints(envelope("Read Shopify orders and update Google Sheets."), sources), ["Shopify", "Google Sheets"]);
});

test("a shared provider family does not select every sibling app", () => {
  assert.deepEqual(
    promptToolHints("Read Google Drive files and calendar, then draft emails in Gmail", catalog),
    ["Google Drive", "Google Calendar", "Gmail"],
  );
});

test("four app request offers the four explicit apps without selecting unrelated Google apps", () => {
  assert.deepEqual(
    promptToolHints("Create a Google Doc and calendar event, a Canva slide, and email me in Gmail", catalog),
    ["Google Docs", "Google Calendar", "Canva", "Gmail"],
  );
});

test("prompt hints are offered as choices instead of being silently selected", () => {
  assert.deepEqual(
    promptToolChoices(["AURA Weather", "Canva", "Gmail"]),
    [
      { label: "AURA Weather", suggested: true, selected: false },
      { label: "Canva", suggested: true, selected: false },
      { label: "Gmail", suggested: true, selected: false },
    ],
  );
});

test("selected, dismissed, and manually added tools keep distinct states", () => {
  assert.deepEqual(
    promptToolChoices(
      ["AURA Weather", "Canva", "Gmail"],
      ["Canva", "Marketing Agent"],
      ["Gmail"],
    ),
    [
      { label: "AURA Weather", suggested: true, selected: false },
      { label: "Canva", suggested: true, selected: true },
      { label: "Marketing Agent", suggested: false, selected: true },
    ],
  );
});
