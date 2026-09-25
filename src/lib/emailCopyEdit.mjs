import { assertReferencesPreserved } from "./canvaCopyEdit.mjs";

export const emailCopySchema = {
  type: "object",
  additionalProperties: false,
  required: ["subject", "body"],
  properties: { subject: { type: "string" }, body: { type: "string" } },
};

export function applyEmailCopy(args, suggestion) {
  if (!suggestion || typeof suggestion.subject !== "string" || typeof suggestion.body !== "string") {
    throw new Error("AURA could not update the email. Please try again or edit the message directly.");
  }
  assertReferencesPreserved(args.subject, suggestion.subject);
  assertReferencesPreserved(args.body, suggestion.body);
  return { ...args, subject: suggestion.subject, body: suggestion.body };
}
