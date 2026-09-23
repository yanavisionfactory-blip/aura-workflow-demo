import test from "node:test";
import assert from "node:assert/strict";

import { instantLanguagePlan, languageDraftPrompt } from "../src/lib/languagePlan.mjs";

const catalog = [
  { name: "Canva", provider: "canva", aliases: ["Canva"] },
  { name: "Linear", provider: "linear", aliases: ["Linear"] },
  { name: "Slack", provider: "slack", aliases: ["Slack"] },
  { name: "AURA Weather", provider: "aura-weather", aliases: ["weather"] },
];

test("a readable plan exists immediately without connector state", () => {
  const plan = instantLanguagePlan(
    "Read my open Linear issues, summarize them, and post the summary to Slack",
    catalog,
  );

  assert.equal(plan.provisional, true);
  assert.equal(plan.compileState, "validating");
  assert.deepEqual(plan.steps.map((step) => step.tool), [
    "Linear",
    "AURA Intelligence",
    "Slack",
  ]);
  assert.equal(plan.steps.at(-1).riskLevel, "modify");
});

test("semantic intent creates useful steps even without explicit provider names", () => {
  const plan = instantLanguagePlan(
    "Prepare a presentation about tomorrow's weather",
    catalog,
  );

  assert.ok(plan.steps.some((step) => step.tool === "Canva"));
  assert.ok(plan.steps.some((step) => step.tool === "AURA Weather"));
});

test("the model refinement contract explicitly ignores connection readiness", () => {
  const prompt = languageDraftPrompt("Read Notion and create Jira tasks");
  assert.match(prompt, /missing connection must never prevent the plan/i);
  assert.match(prompt, /Do not check connections/i);
});

test("a four-app creation request marks every external action for review", () => {
  const apps = ["Google Docs", "Google Calendar", "Canva", "Gmail"];
  const plan = instantLanguagePlan(
    "Create a Google Doc; create a Google Calendar event; create a Canva presentation; send a Gmail message to me",
    apps.map((name) => ({ name, provider: name === "Canva" ? "canva" : "google" })),
    apps,
  );

  assert.deepEqual(plan.steps.map((item) => item.tool), apps);
  assert.deepEqual(plan.steps.map((item) => item.riskLevel), ["modify", "modify", "modify", "modify"]);
  assert.ok(plan.steps.every((item) => item.riskNote.includes("review")));
});

test("a read followed by another app's write stays a read", () => {
  const plan = instantLanguagePlan(
    "Read Google Calendar and create a Canva slide",
    ["Google Calendar", "Canva"].map((name) => ({ name })),
    ["Google Calendar", "Canva"],
  );
  assert.deepEqual(plan.steps.map((item) => item.riskLevel), ["read", "modify"]);
});

test("a tool-only request uses plain descriptions without inventing chosen items", () => {
  const apps = ["Google Docs", "Google Calendar", "Canva", "Gmail"];
  const plan = instantLanguagePlan(
    "Smoke test using Google Docs, Google Calendar, Canva, Gmail",
    apps.map((name) => ({ name })), apps,
  );
  assert.deepEqual(plan.steps.map((item) => item.title), [
    "Read the relevant document", "Check the calendar", "Review the Canva design", "Read the relevant email",
  ]);
  assert.ok(plan.steps.every((item) => item.iWill.includes("you specify")));
});
