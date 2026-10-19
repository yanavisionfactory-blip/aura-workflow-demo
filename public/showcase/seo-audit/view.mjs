export const originalPrompt = `Prepare an SEO audit review package for one Mantas Auk client.

Tools publicly named as audit inputs:

- Semrush: keyword, competitor, ranking and backlink research.
- Ahrefs: competitor search visibility and backlink analysis.
- Screaming Frog: website crawling and technical SEO checks.
- Sitebulb: website crawling and technical audit findings.
- Reporting and task-management destinations: confirm their names.

Use supplied exports or verified connections. Confirm the client website, business goals and export dates.

Normalize URLs, combine overlapping findings and preserve source evidence. Group issues into technical SEO, content, internal linking and backlinks.

Deliver a prioritized roadmap and implementation backlog with affected URLs, evidence, proposed fixes, effort, dependencies and reasoning. Flag contradictions and checks requiring expert review. Do not modify the website.`;

export const initialState = { phase: "brief", tool: "crawl", page: 0, group: "All", task: "T01" };
export const tour = [
  { title: "Start with the brief", caption: "One audit brief. The expected output is evidence, priorities and proposed implementation work.", state: { phase: "brief" }, pointer: [880, 596] },
  { title: "Review the inputs", caption: "The plan distinguishes a real crawl export from three simulated research sources.", state: { phase: "plan" }, pointer: [865, 638] },
  { title: "See the final result", caption: "171 real URL records, 82 canonical conflicts, and a ten-item backlog. Open the evidence behind each tool.", state: { phase: "results" }, pointer: [922, 390] },
  { title: "Inspect Screaming Frog", caption: "The canonical conflict is real. Each affected URL retains its original CSV row; the client is anonymized.", state: { phase: "tool", tool: "crawl" }, pointer: [529, 195] },
  { title: "Review search demand", caption: "The Semrush scenario maps illustrative rankings to real page paths. All research metrics are labelled simulated.", state: { phase: "tool", tool: "semrush" }, pointer: [758, 195] },
  { title: "Inspect backlink evidence", caption: "The Ahrefs example includes a visibility trend and fictional referring domains, with real target paths.", state: { phase: "tool", tool: "ahrefs" }, pointer: [987, 195] },
  { title: "Compare technical findings", caption: "Sitebulb examples distinguish reused crawl evidence from hypothetical orphan and language checks.", state: { phase: "tool", tool: "sitebulb" }, pointer: [767, 96] },
  { title: "Turn findings into work", caption: "The first priority links the real canonical issue to a fix, effort, dependencies and an acceptance check.", state: { phase: "backlog", group: "All", task: "T01" }, pointer: [637, 221] },
  { title: "Keep expert review visible", caption: "Content work remains a proposal. Financial claims and Spanish-language wording need specialist review.", state: { phase: "backlog", group: "Content", task: "C01" }, pointer: [893, 96] },
  { title: "Show the limits", caption: "Source dates, duplicate exports and missing link edges stay visible. Simulated tool agreement is not corroboration.", state: { phase: "sources" }, pointer: [1174, 96] },
  { title: "Ask for feedback", caption: "The question for a practitioner: what would you change first before using this in a real audit review?", state: { phase: "feedback" }, pointer: [417, 561] },
];

export function nextState(state, action, data) {
  if (["brief", "plan", "results", "backlog", "sources", "feedback"].includes(action)) return { ...state, phase: action, page: 0 };
  if (action.startsWith("tool:")) {
    const tool = action.slice(5);
    if (["crawl", "semrush", "ahrefs", "sitebulb"].includes(tool)) return { ...state, phase: "tool", tool, page: 0 };
  }
  if (action.startsWith("task:")) {
    const task = action.slice(5);
    if (data.backlog.some((item) => item.id === task)) return { ...state, phase: "backlog", task };
  }
  if (action.startsWith("group:")) {
    const group = action.slice(6);
    if (["All", "Technical SEO", "Content", "Internal linking", "Backlinks"].includes(group)) {
      const task = data.backlog.find((item) => group === "All" || item.group === group)?.id || "T01";
      return { ...state, phase: "backlog", group, task };
    }
  }
  if (action === "next-page") return { ...state, page: state.page + 1 };
  if (action === "previous-page") return { ...state, page: Math.max(0, state.page - 1) };
  return state;
}

const C = { bg: "#080e1d", panel: "#101a2c", panel2: "#142035", stroke: "#25324a", text: "#f1f5fb", muted: "#91a0b7", faint: "#65758f", primary: "#9a94ff", green: "#5ce0bb", amber: "#f5c475", purple: "#c5a5ff" };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[char]);
const cut = (value, count = 65) => String(value || "").length > count ? `${String(value).slice(0, count - 1)}…` : String(value || "");
const path = (value) => { try { return new URL(value).pathname; } catch { return value || "Not mapped"; } };
const rect = (x, y, w, h, fill = C.panel, stroke = C.stroke, r = 14) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}"/>`;
const text = (x, y, value, size = 14, fill = C.text, weight = 400, anchor = "start") => `<text font-family="Arial" x="${x}" y="${y}" fill="${fill}" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}">${esc(value)}</text>`;
function wrap(value, chars = 68, max = 4) {
  const words = String(value || "").split(/\s+/); const lines = []; let line = "";
  for (const word of words) { if (line.length + word.length + 1 > chars && line) { lines.push(line); line = word; } else line += `${line ? " " : ""}${word}`; }
  if (line) lines.push(line);
  return lines.length > max ? [...lines.slice(0, max - 1), cut(lines.slice(max - 1).join(" "), chars)] : lines;
}
const paragraph = (x, y, value, chars = 68, max = 4, size = 14, fill = C.muted, leading = 22) => wrap(value, chars, max).map((line, i) => text(x, y + i * leading, line, size, fill)).join("");
const button = (x, y, w, label, action, primary = false, height = 36) => `<g role="button" tabindex="0" data-action="${esc(action)}" aria-label="${esc(label)}" class="hit">${rect(x, y, w, height, primary ? "#766bea" : C.panel2, primary ? "#a59aff" : C.stroke, 10)}${text(x + w / 2, y + height / 2 + 5, label, 13, primary ? "#fff" : C.primary, 600, "middle")}</g>`;
const badge = (x, y, label, real = false, w = 114) => `${rect(x, y, w, 26, real ? "#12302f" : "#26213e", real ? "#24524b" : "#4a3c64", 13)}${text(x + w / 2, y + 17, label, 11, real ? C.green : C.purple, 600, "middle")}`;
const heading = (title, subtitle) => text(640, 169, title, 27, C.text, 650, "middle") + text(640, 198, subtitle, 13, C.muted, 400, "middle");
const metrics = (items, x = 300, y = 234, w = 680) => items.map((item, i) => {
  const width = (w - 24) / 3; const left = x + i * (width + 12);
  return rect(left, y, width, 78) + text(left + 18, y + 36, item.value, 27, C.text, 650) + text(left + 18, y + 59, item.label, 11, C.muted);
}).join("");
const toolNames = { crawl: "Screaming Frog", semrush: "Semrush", ahrefs: "Ahrefs", sitebulb: "Sitebulb" };

function header(state) {
  const active = state.phase === "tool" ? "results" : state.phase;
  return rect(0, 0, 1280, 66, "#0b1323", "#202b40", 0) + `<rect x="34" y="18" width="31" height="31" rx="9" fill="#7b6ae4"/><path d="M49.5 24 L52.5 31.5 L60 34.5 L52.5 37.5 L49.5 45 L46.5 37.5 L39 34.5 L46.5 31.5 Z" fill="#fff"/>` + text(78, 40, "AURA", 22, C.text, 650) + badge(150, 21, "INTERACTIVE DEMO", false, 154) + text(1247, 39, "1 real export · 3 simulated tools", 12, C.muted, 400, "end") + ["brief", "plan", "results", "backlog", "sources"].map((phase, i) => button(331 + i * 126, 80, 114, ({ brief: "The brief", plan: "The plan", results: "Results", backlog: "Backlog", sources: "Sources" })[phase], phase, active === phase, 32)).join("") + button(1098, 80, 148, "Give feedback", "feedback", state.phase === "feedback", 32);
}

function brief() {
  return heading("What would you like to do?", "One SEO audit review, from source evidence to proposed implementation work.") + rect(300, 236, 680, 286) + text(326, 273, "Prepare an SEO audit review package", 19, C.text, 600) + paragraph(326, 309, "Use Semrush, Ahrefs, Screaming Frog and Sitebulb. Normalize URLs, combine overlapping findings and preserve source evidence.", 78, 3, 14) + paragraph(326, 386, "Deliver a prioritized roadmap and implementation backlog with affected URLs, evidence, fixes, effort, dependencies and reasoning. Do not modify the website.", 78, 3, 14) + button(326, 468, 168, "Read the full brief", "inspect:brief") + badge(300, 545, "REAL CRAWL EXPORT", true, 172) + badge(482, 545, "3 SAMPLE TOOL OUTPUTS", false, 203) + text(300, 601, "Client anonymized · goals remain provisional · no website changes", 12, C.muted) + button(776, 574, 204, "Review workflow →", "plan", true, 44);
}

function plan(data) {
  return heading("Review the workflow", "The example is explicit about what is real and what is simulated.") + [
    ["crawl", "Import the supplied CSV exports", "171 records; original row evidence retained", true],
    ["semrush", "Review keyword and competitor research", "Illustrative rankings, volume and competition", false],
    ["ahrefs", "Inspect visibility and backlink research", "Fictional referring domains and sample metrics", false],
    ["sitebulb", "Compare technical audit findings", "Derived examples plus hypothetical checks", false],
  ].map(([key, title, subtitle, real], i) => {
    const y = 238 + i * 78;
    return rect(300, y, 680, 68) + text(322, y + 26, toolNames[key], 14, C.text, 600) + text(322, y + 49, subtitle, 12, C.muted) + badge(807, y + 21, real ? "REAL EXPORT" : "SIMULATED", real, 151);
  }).join("") + text(300, 591, "Normalize URLs → merge overlapping findings → propose the implementation backlog", 12, C.muted) + button(300, 616, 180, "Inspect source dates", "sources") + button(758, 616, 222, "Open the audit result →", "results", true, 44);
}

function results(data) {
  return heading("SEO audit review prepared", "Anonymized client · real Screaming Frog evidence + simulated research") + metrics([{ value: data.crawl.counts.url_records, label: "real crawl URL records" }, { value: data.crawl.counts.canonical_conflicts, label: "real canonical conflicts" }, { value: data.backlog.length, label: "proposed backlog items" }]) + text(300, 348, "What happened", 15, C.text, 600) + ["crawl", "semrush", "ahrefs", "sitebulb"].map((key, i) => {
    const y = 365 + i * 58; const real = key === "crawl";
    const messages = { crawl: "171 URL records imported · original source rows retained", semrush: "Sample keyword positions and competitor visibility", ahrefs: "Sample backlinks, referring domains and visibility trend", sitebulb: "Example technical hints and checks requiring validation" };
    return rect(300, y, 680, 50) + `<circle cx="322" cy="${y + 24}" r="6" fill="${real ? C.green : C.purple}"/>` + text(340, y + 21, `${toolNames[key]}${real ? " · real export" : " · simulated"}`, 13, C.text, 600) + text(340, y + 39, messages[key], 10.5, C.muted) + button(865, y + 10, 101, "View output", `tool:${key}`, false, 30);
  }).join("") + rect(300, 609, 680, 53) + text(322, 632, "10 implementation items prepared", 13, C.text, 600) + text(322, 650, "Affected URLs, evidence, fixes, effort, dependencies and expert checks.", 10.5, C.muted) + button(842, 620, 124, "View backlog", "backlog", false, 30) + text(300, 690, "Tools used", 12, C.muted, 600) + ["crawl", "semrush", "ahrefs", "sitebulb"].map((key, i) => button(390 + i * 148, 671, 138, toolNames[key], `tool:${key}`, false, 32)).join("");
}

function table(x, y, widths, headers, rows, actionPrefix = null) {
  const width = widths.reduce((sum, value) => sum + value, 0);
  let out = rect(x, y, width, 37 + rows.length * 44, C.panel, C.stroke, 10) + rect(x, y, width, 36, C.panel2, C.panel2, 10);
  let left = x;
  headers.forEach((label, i) => { out += text(left + 12, y + 23, label, 11, C.muted, 600); left += widths[i]; });
  rows.forEach((row, i) => {
    const top = y + 37 + i * 44;
    let content = `<path d="M${x} ${top} H${x + width}" stroke="${C.stroke}"/>`;
    let colX = x;
    row.forEach((value, col) => { content += text(colX + 12, top + 27, cut(value, Math.max(6, Math.floor((widths[col] - 22) / 6.5))), 11.5, col === 0 ? C.text : C.muted); colX += widths[col]; });
    out += actionPrefix ? `<g data-action="${actionPrefix}:${i}" tabindex="0" role="button" aria-label="Inspect row ${i + 1}" class="hit"><rect x="${x}" y="${top}" width="${width}" height="44" fill="${C.panel}"/>${content}</g>` : content;
  });
  return out;
}

function toolView(data, state) {
  const key = state.tool; const real = key === "crawl"; const source = data.tools.find((item) => item.key === key);
  let out = text(190, 158, `${toolNames[key]} output`, 24, C.text, 650) + badge(920, 137, real ? "REAL CSV EVIDENCE" : "SIMULATED OUTPUT", real, 171) + ["crawl", "semrush", "ahrefs", "sitebulb"].map((tool, i) => button(190 + i * 230, 178, 215, toolNames[tool], `tool:${tool}`, key === tool, 34)).join("");
  if (real) {
    const rows = data.crawl.issues.find((item) => item.id === "T01").affected;
    const page = Math.min(state.page, Math.max(0, Math.ceil(rows.length / 6) - 1));
    out += metrics([{ value: data.crawl.counts.url_records, label: "real URL records" }, { value: rows.length, label: "canonical / redirect conflicts" }, { value: data.crawl.counts.indexable_html, label: "crawler-labelled indexable HTML" }], 190, 233, 900) + text(190, 346, "Canonical URL redirects back to the declaring 200 URL", 16, C.text, 600) + text(190, 370, "A real signal conflict. Not an HTTP loop or proof of Google exclusion. Click a row for full evidence.", 12, C.muted) + table(190, 391, [360, 360, 180], ["200 page path", "Declared canonical path", "Original CSV rows"], rows.slice(page * 6, page * 6 + 6).map((row) => [path(row.url), path(row.canonical), `${row.csv_row} / ${row.canonical_csv_row}`]), "inspect:canonical") + text(190, 722, `${page * 6 + 1}–${Math.min((page + 1) * 6, rows.length)} of ${rows.length} real findings · client.example is an anonymized host`, 11, C.muted) + (page > 0 ? button(873, 699, 99, "Previous", "previous-page", false, 31) : "") + (page < Math.ceil(rows.length / 6) - 1 ? button(985, 699, 105, "Next URLs", "next-page", false, 31) : "");
  } else if (key === "semrush") {
    const page = Math.min(state.page, 1);
    out += metrics(source.metrics, 190, 233, 900) + text(190, 345, "Keyword positions · 12 sample rows", 16, C.text, 600) + text(190, 368, "Volumes, rankings and changes are simulated. Target page paths are from the real crawl.", 12, C.purple) + table(190, 389, [280, 95, 65, 65, 90, 305], ["Query", "US volume", "KD", "Rank", "Change", "Mapped real page path"], source.keywords.slice(page * 6, page * 6 + 6).map((row) => [row.keyword, row.volume, row.difficulty, row.position, `${row.change >= 0 ? "+" : ""}${row.change}`, path(row.url)]), "inspect:keyword") + button(190, 699, 212, "Competitor visibility examples", "inspect:competitors", false, 31) + button(925, 699, 165, page ? "Previous keywords" : "More keywords", page ? "previous-page" : "next-page", false, 31);
  } else if (key === "ahrefs") {
    out += metrics(source.metrics, 190, 233, 900) + text(190, 345, "Backlink sample · fictional .example sources", 16, C.text, 600) + table(190, 369, [342, 48, 92, 98], ["Referring domain / path", "DR", "Link", "State"], source.backlinks.map((row) => [row.source.replace("https://", ""), row.rating, row.follow, row.status]), "inspect:backlink") + rect(796, 369, 294, 301) + text(817, 400, "Visibility trend · simulated", 14, C.text, 600) + text(817, 425, "Estimated visits / month", 11, C.muted);
    source.visibility.forEach((row, i) => { const x = 818 + i * 42; const height = row.traffic * 1.5; out += `<rect x="${x}" y="${602 - height}" width="27" height="${height}" rx="4" fill="#9585ea"/>` + text(x + 13, 590 - height, row.traffic, 10, C.muted, 400, "middle") + text(x + 13, 625, row.month, 10, C.muted, 400, "middle"); });
    out += text(190, 704, "Six fictional samples from a simulated 96 links / 44 domains. No toxicity or disavow conclusion.", 11, C.purple);
  } else {
    out += metrics(source.metrics, 190, 233, 900) + text(190, 345, "Technical hint groups · simulated Sitebulb output", 16, C.text, 600);
    source.hints.forEach((hint, i) => { const y = 365 + i * 64; out += rect(190, y, 900, 56) + text(208, y + 23, `${hint.id} · ${hint.title}`, 13, C.text, 600) + text(208, y + 43, i === 2 || i === 3 ? "HYPOTHETICAL · requires actual crawl validation" : "DERIVED EXAMPLE · reuses real Screaming Frog rows", 10, i === 2 || i === 3 ? C.amber : C.purple) + text(910, y + 32, `${hint.affected.length} URLs`, 12, C.muted, 500, "end") + button(934, y + 13, 140, "Inspect finding", `inspect:hint:${i}`, false, 30); });
    out += text(190, 710, "No Sitebulb crawl was performed. Reused counts are not independent corroboration.", 11, C.purple);
  }
  return out;
}

function backlogView(data, state) {
  const items = data.backlog.filter((item) => state.group === "All" || item.group === state.group);
  const task = items.find((item) => item.id === state.task) || items[0];
  let out = text(160, 159, "Implementation backlog", 24, C.text, 650) + text(160, 185, "10 proposed items · P1 → P2 → P3 · scoped URLs can overlap · no tasks created", 12, C.muted);
  ["All", "Technical SEO", "Content", "Internal linking", "Backlinks"].forEach((name, i) => { out += button(160 + i * 193, 205, 180, name, `group:${name}`, state.group === name, 32); });
  items.forEach((item, i) => { const y = 258 + i * 41; out += `<g role="button" tabindex="0" data-action="task:${esc(item.id)}" class="hit" aria-label="Open ${esc(item.id)}">${rect(160, y, 356, 36, item.id === task.id ? "#25213f" : C.panel, item.id === task.id ? "#7463af" : C.stroke, 8)}${text(171, y + 24, item.priority, 11, item.priority === "P1" ? C.amber : C.muted, 600)}${text(204, y + 24, `${item.id} · ${cut(item.title, 42)}`, 11, C.text)}</g>`; });
  if (!task) return out;
  out += rect(540, 258, 580, 438) + text(560, 288, `${task.id} · ${task.priority} · ${task.group}`, 12, C.primary, 600) + paragraph(560, 319, task.title, 53, 2, 17, C.text, 23) + badge(560, 365, task.kind.startsWith("Simulated") ? "SIMULATED RECOMMENDATION" : "REAL CRAWL EVIDENCE", !task.kind.startsWith("Simulated"), 244) + text(1098, 383, `${task.affected.length} URL records`, 11, C.muted, 400, "end") + text(560, 420, "EVIDENCE", 10, C.primary, 650) + paragraph(560, 441, task.evidence, 78, 2, 12, C.muted, 18) + text(560, 498, "PROPOSED FIX", 10, C.primary, 650) + paragraph(560, 519, task.fix, 78, 3, 12, C.text, 18) + text(560, 592, "EFFORT & DEPENDENCIES", 10, C.primary, 650) + paragraph(560, 613, `${task.effort} · ${task.dependencies}`, 78, 2, 12, C.muted, 18) + button(560, 650, 253, "Inspect complete implementation item", `inspect:task:${task.id}`, false, 30) + text(160, 720, "Every item includes evidence, fix, effort, dependencies, priority reasoning, expert review and an acceptance check.", 11, C.muted);
  return out;
}

function sources(data) {
  return heading("Evidence and limits stay visible", "Separate observed crawl findings, illustrative metrics and checks requiring expert review.") + rect(190, 233, 900, 171) + text(212, 267, "Screaming Frog · real supplied exports", 17, C.text, 600) + text(212, 296, `Raw crawl dates: ${data.crawl.crawl_period.first_raw} → ${data.crawl.crawl_period.last_raw}`, 12, C.muted) + text(212, 321, "Timezone, export creation date and crawl settings were not supplied.", 12, C.muted) + text(212, 348, "internal_all.csv and allinlinks.csv are byte-identical; detailed link edges are missing.", 12, C.amber) + button(212, 365, 195, "Inspect source file hashes", "inspect:files", false, 28) + rect(190, 421, 900, 132) + text(212, 453, "Illustrative tool differences", 17, C.text, 600) + paragraph(212, 480, "Semrush: 42 keywords / 96 visits. Ahrefs: 38 / 84. These simulated estimates illustrate differing coverage. Sitebulb reuses real crawl counts; this does not independently confirm the finding.", 117, 3, 12, C.muted, 20) + rect(190, 570, 900, 114) + text(212, 603, "Client, goals and destinations", 17, C.text, 600) + paragraph(212, 630, "Client identity is anonymized; business goals and KPIs need owner confirmation. Google Docs and Jira are destination examples. No external records or website changes are made.", 118, 3, 12, C.muted, 20) + button(190, 702, 211, "Original workflow brief", "inspect:brief", false, 30);
}

function feedback() {
  return heading("What would you change first?", "Help shape the next version with one concrete observation.") + rect(300, 244, 680, 272) + text(329, 283, "Imagine reviewing this with a client.", 20, C.text, 600) + paragraph(329, 323, "1. Does the final result give you enough evidence to trust the priorities?", 72, 2, 16, C.muted, 24) + paragraph(329, 390, "2. Which handoff from finding to implementation still needs work?", 72, 2, 16, C.muted, 24) + paragraph(329, 456, "3. What is the most important thing missing?", 72, 2, 16, C.muted, 24) + button(300, 540, 217, "Write a short response", "inspect:feedback", true, 43) + button(534, 540, 202, "Explore results again", "results", false, 43) + text(300, 625, "Feedback stays in your browser until you choose to copy it into your email reply.", 12, C.muted);
}

export function renderFrame(data, state = initialState, options = {}) {
  let body = header(state);
  if (state.phase === "brief") body += brief();
  else if (state.phase === "plan") body += plan(data);
  else if (state.phase === "results") body += results(data);
  else if (state.phase === "tool") body += toolView(data, state);
  else if (state.phase === "backlog") body += backlogView(data, state);
  else if (state.phase === "sources") body += sources(data);
  else if (state.phase === "feedback") body += feedback();
  if (options.caption) {
    body += rect(0, 748, 1280, 72, "#141a30", "#3a3556", 0) + text(34, 771, `${options.chapter || "WALKTHROUGH"} · STATIC PROTOTYPE`, 10, C.purple, 600) + paragraph(34, 796, options.caption, 155, 1, 14, C.text, 20);
  } else body += text(640, 791, "READ-ONLY DEMO · CLIENT ANONYMIZED · SIMULATED RESEARCH LABELLED", 10, C.faint, 500, "middle");
  if (options.pointer) { const [x, y] = options.pointer; body += `<circle cx="${x}" cy="${y}" r="18" fill="#a591ff" opacity=".18"/><path d="M${x} ${y} l0 23 6 -6 5 11 5 -2 -5 -10 9 -1 Z" fill="#fff" stroke="#0a1020" stroke-width="2"/>`; }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 820" role="group" aria-label="AURA SEO audit interactive prototype" font-family="DejaVu Sans, Arial, sans-serif"><defs><linearGradient id="brand"><stop stop-color="#7c70ed"/><stop offset="1" stop-color="#3ebfee"/></linearGradient></defs><rect width="1280" height="820" fill="${C.bg}"/>${body}</svg>`;
}
