import data from "./data.mjs";
import { initialState, nextState, renderFrame, tour, originalPrompt } from "./view.mjs";

const $ = (selector) => document.querySelector(selector);
let state = { ...initialState };
let tourIndex = -1;
let playing = false;
let timer = null;
let elapsed = 0;
const chapterMs = 6000;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const fields = (object) => Object.entries(object).map(([name, value]) => `<p><strong>${esc(name.replaceAll("_", " "))}</strong><br>${esc(Array.isArray(value) ? value.join(" · ") : value)}</p>`).join("");
const rows = (records) => `<table><thead><tr><th>Actual anonymized page URL</th><th>Original CSV row</th></tr></thead><tbody>${records.map((row) => `<tr><td>${esc(row.url)}</td><td>${esc(row.csv_row)}</td></tr>`).join("")}</tbody></table>`;

function render() {
  const chapter = tourIndex >= 0 ? tour[tourIndex] : null;
  $("#screen").innerHTML = renderFrame(data, state, chapter ? { caption: chapter.caption, chapter: `${tourIndex + 1} / ${tour.length}` } : {});
  $("#tour-number").textContent = chapter ? `${tourIndex + 1} / ${tour.length}` : "EXPLORE";
  $("#tour-title").textContent = chapter ? chapter.title : "Start with the brief, or jump to the result.";
  $("#tour-toggle").textContent = playing ? "Pause tour" : tourIndex >= 0 ? "Resume tour" : "Play tour";
  $("#progress").style.width = `${tourIndex < 0 ? 0 : (tourIndex + elapsed / chapterMs) / tour.length * 100}%`;
  $("#status").textContent = chapter ? `${chapter.title}. ${chapter.caption}` : `Showing ${state.phase === "tool" ? state.tool + " output" : state.phase}.`;
}

function pause() { playing = false; clearInterval(timer); timer = null; $("#tour-toggle").textContent = tourIndex >= 0 ? "Resume tour" : "Play tour"; }
function chapter(index) {
  tourIndex = Math.max(0, Math.min(tour.length - 1, index));
  state = { ...initialState, ...tour[tourIndex].state };
  elapsed = 0; render();
}
function play(restart = false) {
  pause();
  if (restart || tourIndex < 0 || (tourIndex === tour.length - 1 && elapsed >= chapterMs)) chapter(0);
  playing = true; render();
  timer = setInterval(() => {
    elapsed += 200;
    if (elapsed >= chapterMs && tourIndex < tour.length - 1) chapter(tourIndex + 1);
    else if (elapsed >= chapterMs) { pause(); $("#progress").style.width = "100%"; return; }
    $("#progress").style.width = `${(tourIndex + elapsed / chapterMs) / tour.length * 100}%`;
  }, 200);
}

function detail(title, html) { pause(); $("#detail-title").textContent = title; $("#detail-body").innerHTML = html; $("#detail").showModal(); }
function inspect(action) {
  const [, kind, key] = action.split(":");
  const semrush = data.tools.find((tool) => tool.key === "semrush");
  const ahrefs = data.tools.find((tool) => tool.key === "ahrefs");
  if (kind === "brief") return detail("Original workflow brief", `<p class="notice">Original prompt preserved verbatim. This public prototype is read-only and anonymizes the client; it does not establish an actual client relationship.</p><pre>${esc(originalPrompt)}</pre>`);
  if (kind === "canonical") {
    const issue = data.crawl.issues.find((item) => item.id === "T01");
    const page = Math.min(state.page, Math.ceil(issue.affected.length / 6) - 1);
    return detail("Screaming Frog · real canonical evidence", fields(issue.affected[page * 6 + Number(key)]) + `<p class="notice">Real CSV-derived signal conflict. No HTTP redirect loop or Google exclusion is established. Client host anonymized.</p>`);
  }
  if (kind === "keyword") return detail("Semrush · simulated keyword row", `<p class="notice">Rankings, volumes and changes are simulated; the target page and CSV row come from the real anonymized crawl.</p>` + fields(semrush.keywords[Math.min(state.page, 1) * 6 + Number(key)]));
  if (kind === "competitors") return detail("Semrush · simulated competitor visibility", `<p class="notice">These .example domains are fictional. No actual competitor gap is established.</p>` + semrush.competitors.map((item) => fields(item)).join("<hr>"));
  if (kind === "backlink") return detail("Ahrefs · simulated backlink row", `<p class="notice">The referring domain, link and domain metrics are fictional. The target path is from the real crawl. No outreach or disavow is performed.</p>` + fields(ahrefs.backlinks[Number(key)]));
  if (kind === "hint") {
    const hint = data.tools.find((tool) => tool.key === "sitebulb").hints[Number(key)];
    return detail(`Sitebulb · simulated ${hint.id}`, fields({ title: hint.title, priority: hint.priority, evidence_basis: hint.basis }) + `<p class="notice">Simulated hint. No Sitebulb audit was run. Affected page paths are real; hypothetical conditions must be verified.</p>` + rows(hint.affected));
  }
  if (kind === "task") {
    const task = data.backlog.find((item) => item.id === key);
    const { affected, affected_csv_rows, ...rest } = task;
    return detail(`${task.id} · ${task.title}`, fields(rest) + rows(affected));
  }
  if (kind === "files") return detail("Real crawl source files", `<p>Raw crawl timestamps: ${esc(data.crawl.crawl_period.first_raw)} to ${esc(data.crawl.crawl_period.last_raw)}. Timezone, export creation date and settings were not supplied. Original CSV attachments are not published in this demo.</p>` + data.crawl.files.map((file) => fields(file)).join("<hr>") + `<p class="notice">The duplicate All Inlinks file is another URL inventory; no valid source/destination link-edge export was supplied.</p>`);
  if (kind === "feedback") {
    detail("Your feedback", `<p>What would you change first before using this in a real client audit review? This response stays on this page; copy it into your email reply when ready.</p><textarea id="feedback-text" aria-label="Your feedback" placeholder="The most useful part was…\nThe most important thing missing is…\nI would change…"></textarea><p><button id="copy-feedback" class="primary">Copy feedback</button> <span id="copy-status" role="status"></span></p>`);
    $("#copy-feedback").addEventListener("click", async () => {
      const value = $("#feedback-text").value.trim();
      if (!value) { $("#copy-status").textContent = "Write a short response first."; return; }
      try { await navigator.clipboard.writeText(value); $("#copy-status").textContent = "Copied. Paste it into your email reply."; }
      catch { $("#feedback-text").select(); $("#copy-status").textContent = "Select and copy the text using your browser."; }
    });
  }
}
function act(action) {
  pause();
  if (action.startsWith("inspect:")) return inspect(action);
  tourIndex = -1;
  state = nextState(state, action, data);
  render();
}
$("#screen").addEventListener("click", (event) => { const target = event.target.closest("[data-action]"); if (target) act(target.dataset.action); });
$("#screen").addEventListener("keydown", (event) => { if (!["Enter", " "].includes(event.key)) return; const target = event.target.closest("[data-action]"); if (target) { event.preventDefault(); act(target.dataset.action); } });
$("#restart").addEventListener("click", () => { pause(); state = { ...initialState }; tourIndex = -1; elapsed = 0; render(); });
$("#play-tour").addEventListener("click", () => play(true));
$("#tour-toggle").addEventListener("click", () => playing ? (pause(), render()) : play());
$("#tour-prev").addEventListener("click", () => { pause(); chapter(tourIndex <= 0 ? 0 : tourIndex - 1); });
$("#tour-next").addEventListener("click", () => { pause(); chapter(tourIndex < 0 ? 0 : tourIndex + 1); });
$("#feedback").addEventListener("click", () => act("feedback"));
$("#close-detail").addEventListener("click", () => $("#detail").close());
$("#watch").addEventListener("click", () => { pause(); $("#movie").showModal(); $("#video").play().catch(() => {}); });
$("#close-movie").addEventListener("click", () => { $("#video").pause(); $("#movie").close(); });
$("#movie").addEventListener("close", () => $("#video").pause());
document.addEventListener("visibilitychange", () => { if (document.hidden) { pause(); render(); } });
render();
