// Report text describes prepared work; only persisted run steps are receipts.
// Source references are IDs, never arbitrary API paths or provider requests.
const uuid = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const isRunId = (value) => typeof value === "string" && new RegExp(`^${uuid}$`, "i").test(value);

export function campaignSourceRunIds(sources = []) {
  const ids = [];
  for (const source of sources) {
    if (typeof source.content !== "string") continue;
    try {
      const data = JSON.parse(source.content);
      for (const key of ["native_source_run", "source_run_id"]) if (isRunId(data?.[key])) ids.push(data[key]);
    } catch { /* Existing saved packets can have explicit textual provenance. */ }
    for (const match of source.content.matchAll(new RegExp(`\\bnative (?:source )?run (${uuid})(?=[\\s.,;:]|$)`, "gi"))) ids.push(match[1]);
  }
  return [...new Set(ids.map((id) => id.toLowerCase()))].slice(0, 8);
}

const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map((cell) => cell.trim());

export function campaignDeliveryRows(body = "") {
  const lines = String(body).split("\n");
  const rows = [];
  for (let index = 0; index < lines.length - 2; index++) {
    const header = cells(lines[index]).map((cell) => cell.replace(/\*/g, "").toLowerCase());
    if (header.length !== 4 || !/actual application/.test(header[0]) || !/action completed/.test(header[1])
      || !/saved output/.test(header[2]) || !/remaining action/.test(header[3])
      || !cells(lines[index + 1]).every((cell) => /^:?-{3,}:?$/.test(cell))) continue;
    for (let rowIndex = index + 2; rowIndex < lines.length; rowIndex++) {
      const row = cells(lines[rowIndex]);
      if (row.length !== 4) break;
      rows.push({ application: row[0], completed: row[1], saved: row[2], remaining: row[3] });
    }
    break;
  }
  return rows;
}

export function campaignApplicationGroup(application, available = []) {
  const choices = [
    [/google ads|search/i, "Google Ads"], [/business profile|\bgbp\b/i, "Business Profile"],
    [/meta|facebook|instagram|social|linkedin/i, "Social ads"], [/screen|indoor|signage|\bcms\b/i, "Indoor screens"],
    [/storage|google drive|dropbox|\bbox\b|assets/i, "Assets"],
    [/approval|review process/i, "Approvals"], [/\bpm\b|project|jira|asana|trello/i, "Project management"],
  ];
  const match = choices.find(([pattern]) => pattern.test(application))?.[1];
  if (available.includes(match)) return match;
  if (["Approvals", "Project management"].includes(match) && available.includes("Approvals and handoff")) return "Approvals and handoff";
  return null;
}

const names = { "google-ads": "Google Ads", "google-drive": "Google Drive", "google-business-profile": "Google Business Profile", jira: "Jira", aura: "AURA", web: "Public web" };

export function campaignRunActivity(run) {
  return (run?.steps || []).map((step) => ({
    ...step, stepKey: step.key, tool: names[step.tool_slug] || step.tool_slug || step.tool || "AURA",
    action: step.reason || step.operation || "Saved action",
  }));
}

export function campaignActivityForGroup(activity, group) {
  if (!group || group === "Tool outputs") return activity;
  const patterns = {
    "Google Ads": /google[ -]ads/i,
    "Business Profile": /google[ -]business[ -]profile|businessprofile|\bgbp\b/i,
    "Social ads": /facebook|instagram|meta[ -]ads|linkedin[ -]ads/i,
    "Indoor screens": /screen|signage/i,
    Assets: /google[ -]drive|dropbox|\bbox\b|asset[ -]storage/i,
    Approvals: /approval/i,
    "Project management": /jira|asana|trello|project[ -]management/i,
    "Approvals and handoff": /approval|jira|asana|trello/i,
    "Booking and source checks": /website\.source\.inspect|web\.(?:page\.read|search)|vagaro/i,
  };
  return activity.filter((step) => patterns[group]?.test(`${step.tool || ""} ${step.operation || step.output?.operation || ""}`));
}
