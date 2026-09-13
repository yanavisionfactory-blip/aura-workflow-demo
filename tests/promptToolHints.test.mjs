import test from "node:test";
import assert from "node:assert/strict";

import { promptToolHints } from "../src/lib/promptToolHints.mjs";

const catalog = [
  { name: "Canva", provider: "canva", aliases: ["Canva"] },
  { name: "Gmail", provider: "google", aliases: ["Gmail"] },
  { name: "Linear", provider: "linear", aliases: ["Linear"] },
  { name: "Slack", provider: "slack", aliases: ["Slack"] },
  { name: "Jira", provider: "jira", aliases: ["Jira"] },
  { name: "Google Drive", provider: "google", canonicalProvider: "google", aliases: ["google", "Google Drive"] },
  { name: "Google Calendar", provider: "google", canonicalProvider: "google", aliases: ["google", "Google Calendar"] },
  { name: "Google Sheets", provider: "google", canonicalProvider: "google", aliases: ["google", "Google Sheets"] },
];

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

test("a shared provider family does not select every sibling app", () => {
  assert.deepEqual(
    promptToolHints("Read Google Drive files and calendar, then draft emails in Gmail", catalog),
    ["Google Drive", "Google Calendar", "Gmail"],
  );
});
