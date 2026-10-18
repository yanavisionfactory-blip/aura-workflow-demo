import { assertReferencesPreserved } from "./canvaCopyEdit.mjs";
import { articleWordCount } from "./actionContent.mjs";

export const articleCopySchema = {
  type: "object",
  additionalProperties: false,
  required: ["title", "content"],
  properties: { title: { type: "string" }, content: { type: "string" } },
};

export function applyArticleCopy(args, suggestion) {
  if (!suggestion || typeof suggestion.title !== "string" || !suggestion.title.trim()
      || typeof suggestion.content !== "string" || !suggestion.content.trim()) {
    throw new Error("AURA couldn't apply that revision. Try again or edit the article directly.");
  }
  assertReferencesPreserved(args.title, suggestion.title);
  assertReferencesPreserved(args.content, suggestion.content);
  if (/<\s*(?:script|style|iframe|object|embed|form)\b|\bon\w+\s*=|(?:href|src)\s*=\s*["']?\s*(?:javascript|data):/i.test(suggestion.content)) {
    throw new Error("The revision contains unsupported formatting. Try again or use the article editor.");
  }
  if (articleWordCount(args.content) >= 300 && articleWordCount(suggestion.content) < 300) {
    throw new Error("That revision is incomplete. Your full article is still in the preview.");
  }
  // A wording revision never changes the destination, draft state, metadata or
  // approval settings, even if extra fields appear in the model response.
  return { ...args, title: suggestion.title, content: suggestion.content };
}
