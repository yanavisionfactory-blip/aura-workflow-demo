// Common workflow verbs with explicit past + gerund forms (lowercase first word).
const VERBS = {
  pull: { past: "pulled", ing: "pulling" },
  organize: { past: "organized", ing: "organizing" },
  send: { past: "sent", ing: "sending" },
  create: { past: "created", ing: "creating" },
  update: { past: "updated", ing: "updating" },
  add: { past: "added", ing: "adding" },
  schedule: { past: "scheduled", ing: "scheduling" },
  get: { past: "got", ing: "getting" },
  fetch: { past: "fetched", ing: "fetching" },
  compile: { past: "compiled", ing: "compiling" },
  draft: { past: "drafted", ing: "drafting" },
  route: { past: "routed", ing: "routing" },
  sync: { past: "synced", ing: "syncing" },
  generate: { past: "generated", ing: "generating" },
  build: { past: "built", ing: "building" },
  analyze: { past: "analyzed", ing: "analyzing" },
  summarize: { past: "summarized", ing: "summarizing" },
  convert: { past: "converted", ing: "converting" },
  email: { past: "emailed", ing: "emailing" },
  post: { past: "posted", ing: "posting" },
  delete: { past: "deleted", ing: "deleting" },
  review: { past: "reviewed", ing: "reviewing" },
  prepare: { past: "prepared", ing: "preparing" },
  export: { past: "exported", ing: "exporting" },
  find: { past: "found", ing: "finding" },
  identify: { past: "identified", ing: "identifying" },
  make: { past: "made", ing: "making" },
  write: { past: "wrote", ing: "writing" },
  collect: { past: "collected", ing: "collecting" },
  extract: { past: "extracted", ing: "extracting" },
  process: { past: "processed", ing: "processing" },
  transform: { past: "transformed", ing: "transforming" },
  calculate: { past: "calculated", ing: "calculating" },
  score: { past: "scored", ing: "scoring" },
  filter: { past: "filtered", ing: "filtering" },
  sort: { past: "sorted", ing: "sorting" },
  assign: { past: "assigned", ing: "assigning" },
  notify: { past: "notified", ing: "notifying" },
  invite: { past: "invited", ing: "inviting" },
  log: { past: "logged", ing: "logging" },
  store: { past: "stored", ing: "storing" },
};

function fallbackVerb(word, tense) {
  const lower = word.toLowerCase();
  if (tense === "past") {
    if (/e$/i.test(lower)) return lower + "d";
    if (/[^aeiou]y$/i.test(lower)) return lower.slice(0, -1) + "ied";
    return lower + "ed";
  }
  if (/ie$/i.test(lower)) return lower.slice(0, -2) + "ying";
  if (/e$/i.test(lower)) return lower.slice(0, -1) + "ing";
  return lower + "ing";
}

// Conjugate the leading verb of an action sentence to the requested tense.
// tense: "past" (completed) or "ing" (in progress). Other values return the original.
export function conjugateAction(action, tense) {
  if (!action || (tense !== "past" && tense !== "ing")) return action;
  const match = action.match(/^(\s*)([A-Za-z][\w'-]*)(.*)$/);
  if (!match) return action;
  const [, lead, firstWord, rest] = match;
  const dict = VERBS[firstWord.toLowerCase()];
  let replaced = dict ? (tense === "past" ? dict.past : dict.ing) : fallbackVerb(firstWord, tense);
  if (firstWord[0] === firstWord[0].toUpperCase()) {
    replaced = replaced[0].toUpperCase() + replaced.slice(1);
  }
  return lead + replaced + rest;
}