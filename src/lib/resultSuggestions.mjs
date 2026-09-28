export const RESULT_SUGGESTIONS_SCHEMA = {
  type: "object",
  properties: {
    nextSteps: { type: "array", items: { type: "string" } },
  },
  required: ["nextSteps"],
};

export function normalizeResultSuggestions(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value.flatMap((item) => {
    if (typeof item !== "string") return [];
    const suggestion = item.trim().replace(/\s+/g, " ");
    const key = suggestion.toLocaleLowerCase();
    if (!suggestion || suggestion.length > 140 || seen.has(key)) return [];
    seen.add(key);
    return [suggestion];
  }).slice(0, 3);
}

export function resultSuggestionsPrompt({ prompt, summary, deliverable, title }) {
  return `Suggest optional next workflows for a completed AURA run. This is language generation only; do not run tools or claim that a suggestion has already happened.

Original request: ${String(prompt || "").slice(0, 1500)}
Verified result title: ${String(title || "").slice(0, 200)}
Verified result summary: ${String(summary || "").slice(0, 1500)}
Verified deliverable: ${String(deliverable || "").slice(0, 1500)}

Return JSON with nextSteps containing two or three short, distinct, actionable user requests. Ground each suggestion in the verified result. Suggest a future workflow, not a claim about completed work. Do not invent recipients, dates, resource IDs, or facts. If there is no useful grounded follow-up, return an empty array. Do not include "Run again" or "Schedule" as suggestions.`;
}
