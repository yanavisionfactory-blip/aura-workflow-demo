// Omissions narrow a draft; these aliases never authorize an account.
const family = (value) => {
  const key = String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").replace(/-mcp$/, "");
  return ({ "google-sheets": "sheets", "google-docs": "docs", "google-calendar": "calendar",
    "google-drive": "drive", "google-workspace": "google", "meta-ads-direct": "meta-ads", "slack-v2": "slack" })[key] || key;
};

function instructionText(value) {
  const result = String(value || "").match(/^Revise the selected [^\n]+ result inside AURA\.\s*\nRequested change: ([\s\S]*?)\nSaved result context \(reference data\):/);
  if (result) return result[1];
  return String(value || "").split("\n\nThe user reviewed the proposed workflow and requested this change:")
    .map((part) => part.split("\nCurrent reviewed steps (")[0]).join("\n").trim();
}

export function reconcileToolOmissions(prompt, selected = [], excluded = [], candidates = []) {
  const omissions = new Set(excluded.map(family).filter(Boolean));
  const text = instructionText(prompt);
  const names = new Set([...selected, ...candidates, "Reddit", "LinkedIn", "TikTok"]);
  for (const name of names) {
    const words = String(name || "").toLowerCase().match(/[a-z0-9]+/g);
    if (!words) continue;
    const alias = words.join("[\\s-]+");
    const command = new RegExp(`(?:^|[.!?;\\n]\\s*|requested this change:\\s*)(?:please\\s+)?(?:(?:omit|exclude|run without)\\s+${alias}(?=\\s*(?:[.!?;\\n]|$|and all steps\\b|from (?:the )?(?:plan|workflow)\\b))|replace\\s+${alias}\\s+with\\s+)`, "i");
    if (command.test(text)) omissions.add(family(name));
  }
  for (const brand of ["reddit", "linkedin", "tiktok"]) {
    if (omissions.has(brand)) omissions.add(`${brand}-ads`);
  }
  return {
    selectedTools: selected.filter((name) => !omissions.has(family(name))),
    excludedFamilies: [...omissions].sort(),
  };
}
