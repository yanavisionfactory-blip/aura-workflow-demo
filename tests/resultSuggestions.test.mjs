import test from "node:test";
import assert from "node:assert/strict";
import { normalizeResultSuggestions, resultSuggestionsPrompt } from "../src/lib/resultSuggestions.mjs";

test("suggestions from a completed run are concise, distinct, and safe to render", () => {
  assert.deepEqual(normalizeResultSuggestions([
    "  Summarize the briefing for the team ",
    "summarize the briefing for the team",
    null,
    "Compare it with last week's briefing",
    "x".repeat(141),
    "Create a checklist from the briefing",
    "Unused fourth suggestion",
  ]), [
    "Summarize the briefing for the team",
    "Compare it with last week's briefing",
    "Create a checklist from the briefing",
  ]);
  assert.deepEqual(normalizeResultSuggestions(undefined), []);
});

test("fallback LLM sees only the stated intent and verified result", () => {
  const prompt = resultSuggestionsPrompt({
    prompt: "Make a briefing",
    title: "Briefing created",
    summary: "The briefing was saved.",
    deliverable: "A Google Doc is ready.",
  });
  assert.match(prompt, /Original request: Make a briefing/);
  assert.match(prompt, /Verified result summary: The briefing was saved\./);
  assert.match(prompt, /Do not invent recipients, dates, resource IDs, or facts/);
  assert.match(prompt, /Do not include "Run again" or "Schedule"/);
});
