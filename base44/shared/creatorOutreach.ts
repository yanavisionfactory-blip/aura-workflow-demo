// Shared creator-outreach engine for Grail Talent.
//
// Used by TWO entry points so the exact same logic runs whether the user
// triggers it from the AURA plan/approve/results flow (orchestrateWorkflow)
// or from the recurring scheduled job (runCreatorOutreach).
//
// Flow: discover -> dedup -> submit -> draft -> notify. Each phase calls
// onPhase(phase, detail) so callers can show live progress.

const GRAIL_SHEET_ID = "12ChkmVZmBrloAAUFDDeYDSUpMEHjddWjQjKz61Wj-IA";
const SHEET_TAB = "Contacted Creators";
const VERCEL_APP_URL = "https://mgr-approver.vercel.app/";
const VERCEL_ACTION_ID = "40628580cb7e1fb882a6be32de5af4d96890245425";

const DISCOVERY_SCHEMA = {
  type: "object",
  properties: {
    creators: {
      type: "array",
      items: {
        type: "object",
        properties: {
          tiktok_username: { type: "string" },
          full_name: { type: "string" },
          tiktok_url: { type: "string" },
          instagram_username: { type: "string" },
          email: { type: "string" },
          followers: { type: "number" },
          video_count: { type: "number" },
          avg_views: { type: "number" },
          original_audio_pct: { type: "number" },
          is_private: { type: "boolean" },
          is_banned: { type: "boolean" },
          has_management_email_in_bio: { type: "boolean" },
          posted_within_5_days: { type: "boolean" },
          niche: { type: "string" },
          notes: { type: "string" },
        },
      },
    },
  },
};

const DRAFT_SCHEMA = {
  type: "object",
  properties: {
    drafts: {
      type: "array",
      items: {
        type: "object",
        properties: { tiktok_username: { type: "string" }, subject: { type: "string" }, body: { type: "string" } },
      },
    },
  },
};

export function normUser(u) {
  if (!u) return "";
  let s = String(u).trim().toLowerCase().replace(/^https?:\/\/(www\.)?tiktok\.com\//, "");
  if (!s) return "";
  if (!s.startsWith("@")) s = "@" + s;
  return s;
}

async function getToken(base44, type) {
  try {
    const conn = await base44.asServiceRole.connectors.getConnection(type);
    return conn?.accessToken || null;
  } catch {
    return null;
  }
}

// Read a stored API key for a specialized tool (Modash/HypeAuditor/Apify) from
// the ToolConnection meta. Returns null if the user hasn't connected one.
async function getApiKey(base44, toolName) {
  try {
    const conns = await base44.asServiceRole.entities.ToolConnection.filter({ tool_name: toolName }, "-created_date", 1);
    return conns?.[0]?.meta?.apiKey || null;
  } catch {
    return null;
  }
}

// Discover creators via the Modash API. NOTE: verify the exact endpoint/payload
// against https://modash.io/api docs — this is a best-effort scaffold. On any
// error the caller falls back to LLM discovery (marked unverified).
async function discoverViaModash(key, niche, limit = 20) {
  const r = await fetch("https://api.modash.io/v1/creators/search", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ platform: "tiktok", query: niche, limit }),
  });
  if (!r.ok) throw new Error(`Modash ${r.status}`);
  const data = await r.json();
  const rows = data.creators || data.data || [];
  return rows.map((c) => ({
    tiktok_username: c.username || c.handle || c.username_tiktok || "",
    full_name: c.name || c.full_name || "",
    tiktok_url: c.url || `https://www.tiktok.com/@${String(c.username || "").replace(/^@/, "")}`,
    instagram_username: c.instagram || c.instagram_username || "",
    email: c.email || c.contact_email || "",
    followers: c.followers || c.subscribers || 0,
    video_count: c.videos || c.video_count || 0,
    avg_views: c.avg_views || c.average_views || 0,
    original_audio_pct: c.original_audio_pct || (c.original_audio_ratio != null ? Math.round(c.original_audio_ratio * 100) : 0),
    is_private: !!c.is_private,
    is_banned: !!c.is_banned || !!c.is_restricted,
    has_management_email_in_bio: !!c.has_management_email,
    posted_within_5_days: c.last_post_date ? Date.now() - new Date(c.last_post_date).getTime() <= 5 * 86400000 : false,
    niche,
    notes: "Source: Modash (verified)",
  }));
}

async function readContactedUsernames(token) {
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${GRAIL_SHEET_ID}/values/${encodeURIComponent(SHEET_TAB)}!D2:D2000`;
  const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok) throw new Error(`Google Sheets read failed (${r.status})`);
  const data = await r.json();
  const set = new Set();
  for (const row of data.values || []) {
    const u = normUser(row[0]);
    if (u) set.add(u);
  }
  return set;
}

async function fetchActionId() {
  try {
    const html = await (await fetch(VERCEL_APP_URL, { headers: { Accept: "text/html" } })).text();
    const chunk = html.match(/src="(\/_next\/static\/chunks\/app\/page-[^"]+)"/)?.[1];
    if (!chunk) return VERCEL_ACTION_ID;
    const js = await (await fetch(VERCEL_APP_URL + chunk)).text();
    const m = js.match(/createServerReference\("([0-9a-f]{32,64})"/);
    return m ? m[1] : VERCEL_ACTION_ID;
  } catch {
    return VERCEL_ACTION_ID;
  }
}

function buildMultipart(fields) {
  const boundary = "----aura" + Math.random().toString(36).slice(2);
  let parts = "";
  for (const [k, v] of Object.entries(fields)) {
    parts += `--${boundary}\r\nContent-Disposition: form-data; name="${k}"\r\n\r\n${String(v)}\r\n`;
  }
  parts += `--${boundary}--\r\n`;
  return { body: parts, contentType: `multipart/form-data; boundary=${boundary}` };
}

async function submitToApprover({ creatorUsername, managerEmail, creatorEmail, notes }, actionId) {
  const { body, contentType } = buildMultipart({ creatorUsername, managerEmail, creatorEmail: creatorEmail || "", notes: notes || "" });
  const r = await fetch(VERCEL_APP_URL, {
    method: "POST",
    headers: {
      "Next-Action": actionId,
      "Content-Type": contentType,
      "Accept": "text/x-component",
      "Origin": VERCEL_APP_URL.replace(/\/$/, ""),
      "Referer": VERCEL_APP_URL,
      "User-Agent": "Mozilla/5.0 (AURA Outreach Bot)",
    },
    body,
  });
  const text = await r.text();
  return { ok: r.ok, status: r.status, snippet: text.slice(0, 400) };
}

async function fetchGmailSentSamples(token, max = 5) {
  const r = await fetch(`https://gmail.googleapis.com/gmail/v1/users/me/messages?labelIds=SENT&maxResults=${max}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) return [];
  const data = await r.json();
  const out = [];
  for (const m of data.messages || []) {
    const mr = await fetch(`https://gmail.googleapis.com/gmail/v1/users/me/messages/${m.id}?format=full`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!mr.ok) continue;
    const md = await mr.json();
    const subject = (md.payload?.headers || []).find((h) => h.name === "Subject")?.value || "";
    let body = "";
    const part = md.payload?.body?.data || md.payload?.parts?.find((p) => p.mimeType === "text/plain")?.body?.data;
    if (part) {
      try { body = atob(part.replace(/-/g, "+").replace(/_/g, "/")); } catch {}
    }
    out.push({ subject, body: body.slice(0, 1200) });
  }
  return out;
}

async function sendGmail(token, { to, subject, body }) {
  const email = [`To: ${to}`, `Subject: ${subject}`, "Content-Type: text/plain; charset=utf-8", "MIME-Version: 1.0", "", body].join("\r\n");
  const b64 = btoa(unescape(encodeURIComponent(email))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ raw: b64 }),
  });
  return { ok: r.ok, status: r.status };
}

// Detect whether a workflow request is a creator-outreach job.
export function isCreatorOutreachIntent(text) {
  const t = (text || "").toLowerCase();
  return /creator/.test(t) && /tiktok|grail|outreach/.test(t);
}

export async function runCreatorOutreachCore(base44, secrets, opts) {
  const {
    niche = "lifestyle, beauty, travel, and relatable everyday-creator content",
    maxCreators = 5,
    dryRun = false,
    onPhase = () => {},
    emailTemplate = null,
  } = opts || {};

  const sheetsToken = await getToken(base44, "googlesheets");
  const gmailToken = await getToken(base44, "gmail");
  if (!sheetsToken) throw new Error("Google Sheets not connected");
  if (!gmailToken) throw new Error("Gmail not connected");

  // ---- 1. Dedup sets ----
  onPhase("dedup", "Checking Grail's Contacted Creators sheet + prior submissions");
  const contacted = await readContactedUsernames(sheetsToken);
  const prior = await base44.asServiceRole.entities.Creator.filter({}, "-created_date", 1000);
  const existingByUser = new Map((prior || []).map((c) => [normUser(c.tiktok_username), c]));
  const alreadyHandled = new Set(
    (prior || []).filter((c) => ["discovered", "submitted", "approved", "emailed"].includes(c.status)).map((c) => normUser(c.tiktok_username)).filter(Boolean)
  );

  // ---- 2. Discover ----
  // Prefer a real creator-data API (Modash) when connected — it returns
  // VERIFIED stats + contact emails. Without one, fall back to LLM web search
  // and mark every candidate UNVERIFIED (stats may be estimated or wrong).
  const modashKey = await getApiKey(base44, "Modash");
  let candidates = [];
  let verified = false;
  if (modashKey) {
    onPhase("discovery", `Searching Modash for verified TikTok creators in "${niche}"`);
    try {
      candidates = await discoverViaModash(modashKey, niche, 20);
      verified = true;
    } catch (e) {
      onPhase("discovery", `Modash error (${e.message}) — falling back to web search`);
    }
  }
  if (!candidates.length) {
    onPhase("discovery", `Searching the web for TikTok creators in "${niche}"`);
    const discovery = await base44.asServiceRole.integrations.Core.InvokeLLM({
      model: "gemini_3_flash",
      add_context_from_internet: true,
      prompt: `You are AURA, a creator-discovery engine for Grail Talent (a TikTok creator management agency). Find real TikTok creators in this niche: "${niche}".

For each creator, research their actual TikTok presence and return their real stats. Only return creators that plausibly meet ALL of these criteria — and report the real numbers so they can be verified:
1. At least 15,000 followers
2. Account is NOT private
3. Account is NOT banned or restricted
4. At least 10 videos posted
5. NO management email in their bio (no contact@, no agency email — they must be unmanaged)
6. Average of at least 15,000 views per video (excluding the top and bottom 10% of their videos)
7. Uses original audio in at least 30% of their videos
8. Has posted at least once in the past 5 days (posted_within_5_days = true)
9. A reachable creator email can be found — this is MANDATORY. Search their TikTok bio link, their Linktree/Beacons/Stan page, their Instagram contact info, or any public contact page. Put the email in "email". Do NOT include a creator if you cannot find a real, public contact email for them — every creator you return must have a non-empty "email".

Return 10–15 candidates, each with a verified public contact email. Use real TikTok usernames (with the @). Be accurate — do not invent stats or emails; if a number can't be confirmed, estimate conservatively and note it in "notes".`,
      response_json_schema: DISCOVERY_SCHEMA,
    });
    candidates = discovery.creators || [];
    verified = false;
  }
  candidates = candidates.map((c) => ({ ...c, _verified: verified }));

  // ---- 3. Filter ----
  const qualifying = [];
  const skipped = [];
  for (const c of candidates) {
    const u = normUser(c.tiktok_username);
    if (!u) { skipped.push({ username: c.tiktok_username, reason: "no valid username" }); continue; }
    if (contacted.has(u) || alreadyHandled.has(u)) { skipped.push({ username: u, reason: "already in Grail database" }); continue; }
    const fails = [];
    if ((c.followers || 0) < 15000) fails.push("followers < 15k");
    if (c.is_private) fails.push("private account");
    if (c.is_banned) fails.push("banned/restricted");
    if ((c.video_count || 0) < 10) fails.push("< 10 videos");
    if (c.has_management_email_in_bio) fails.push("management email in bio");
    if ((c.avg_views || 0) < 15000) fails.push("avg views < 15k");
    if ((c.original_audio_pct || 0) < 30) fails.push("original audio < 30%");
    if (c.posted_within_5_days === false) fails.push("not posted in 5 days");
    if (fails.length) { skipped.push({ username: u, reason: fails.join("; ") }); continue; }
    if (!c.email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(c.email)) { skipped.push({ username: u, reason: "no valid contact email" }); continue; }
    qualifying.push({ ...c, tiktok_username: u });
    if (qualifying.length >= maxCreators) break;
  }

  if (dryRun) {
    return {
      dryRun: true,
      candidatesCount: candidates.length,
      contactedInSheet: contacted.size,
      alreadyHandled: alreadyHandled.size,
      qualifying,
      skippedCount: skipped.length,
      skippedSample: skipped.slice(0, 12),
      creators: [],
      drafts: [],
    };
  }

  // ---- 4. Persist as discovered (pending manager approval) ----
  onPhase("submit", `Saving ${qualifying.length} qualifying creator${qualifying.length === 1 ? "" : "s"} for your approval`);
  const managerEmail = secrets.get("GRAIL_TALENT_EMAIL");
  if (!managerEmail) throw new Error("GRAIL_TALENT_EMAIL secret not set");
  const created = [];
  for (const c of qualifying) {
    const notes = `Discovered by AURA — niche: ${c.niche || niche}. Followers: ${c.followers}, avg views: ${c.avg_views}, original audio: ${c.original_audio_pct}%.`;
    const fields = {
      tiktok_username: c.tiktok_username,
      full_name: c.full_name || "",
      tiktok_url: c.tiktok_url || `https://www.tiktok.com/${c.tiktok_username}`,
      instagram_username: c.instagram_username || "",
      email: c.email || "",
      followers: c.followers || 0,
      video_count: c.video_count || 0,
      avg_views: c.avg_views || 0,
      original_audio_pct: c.original_audio_pct || 0,
      last_post_date: c.last_post_date || "",
      niche: c.niche || niche,
      status: "discovered",
      submission_date: new Date().toISOString(),
      notes,
      criteria_notes: "passed all 9 criteria",
    };
    const ex = existingByUser.get(c.tiktok_username);
    let id;
    if (ex) { await base44.asServiceRole.entities.Creator.update(ex.id, fields); id = ex.id; }
    else { const rec = await base44.asServiceRole.entities.Creator.create(fields); id = rec.id; }
    created.push({ ...c, id, status: "discovered" });
  }

  // ---- 5. Drafts in the user's Gmail voice ----
  onPhase("draft", `Writing first-outreach drafts for ${created.length} creator${created.length === 1 ? "" : "s"}`);
  const samples = await fetchGmailSentSamples(gmailToken, 5);
  const draftInput = created.map((c) => ({ tiktok_username: c.tiktok_username, full_name: c.full_name, niche: c.niche || niche, tiktok_url: c.tiktok_url }));
  let drafts = [];
  if (draftInput.length) {
    const templateBlock = emailTemplate && (emailTemplate.subject || emailTemplate.body)
      ? `\nThe user has reviewed and EDITED this sample outreach email on the preview screen. Match its tone, structure, and wording closely — customize it per creator (their name, content, niche), but keep the same opening style, length, and sign-off the user chose:\nSubject: ${emailTemplate.subject}\nBody:\n${emailTemplate.body}\n`
      : "";
    const draftRes = await base44.asServiceRole.integrations.Core.InvokeLLM({
      prompt: `You are AURA, writing first-outreach emails from a Grail Talent manager to TikTok creators, inviting them to a partnership conversation.

Write in the EXACT voice and style of these real sent emails from the manager:
${JSON.stringify(samples)}
${templateBlock}
Keep the same tone, length, greeting/sign-off style, and formatting. Each email should be warm, specific to the creator's content, and invite a brief chat about working with Grail. Do NOT promise specific deals.

Write one email per creator:
${JSON.stringify(draftInput)}

Return subject + body for each, keyed by tiktok_username.`,
      response_json_schema: DRAFT_SCHEMA,
    });
    drafts = draftRes.drafts || [];
  }
  for (const d of drafts) {
    const u = normUser(d.tiktok_username);
    const rec = created.find((c) => c.tiktok_username === u);
    if (rec?.id) {
      await base44.asServiceRole.entities.Creator.update(rec.id, { outreach_subject: d.subject || "", outreach_draft: d.body || "" });
      rec.outreach_subject = d.subject || "";
      rec.outreach_draft = d.body || "";
    }
  }

  // ---- 6. Notify the manager ----
  onPhase("notify", "Emailing the manager a summary");
  const lineFor = (c) => {
    const draft = drafts.find((d) => normUser(d.tiktok_username) === c.tiktok_username);
    const head = `• ${c.tiktok_username} (${c.full_name || "—"}) — ${c.tiktok_url}`;
    const draftLine = draft?.subject ? `  Draft subject: ${draft.subject}` : "  (draft pending)";
    return [head, draftLine].filter(Boolean).join("\n");
  };
  const creatorLines = created.map(lineFor).join("\n");
  await sendGmail(gmailToken, {
    to: managerEmail,
    subject: `AURA: ${created.length} new creator${created.length === 1 ? "" : "s"} ready for your approval`,
    body: `Hi,

AURA just ran creator discovery for "${niche}" and found ${created.length} candidate${created.length === 1 ? "" : "s"} that meet all criteria.

Review and approve them in AURA — first-outreach email drafts are ready for each. Once you approve, AURA will send the outreach email automatically.

${creatorLines || "(no qualifying creators this run)"}

You can also check each creator in the Grail approver form (https://mgr-approver.vercel.app/) before approving.

Skipped ${skipped.length} candidate${skipped.length === 1 ? "" : "s"} (already contacted or didn't meet criteria).

— AURA`,
  });

  return {
    candidates: candidates.length,
    contactedInSheet: contacted.size,
    qualifying: qualifying.length,
    discovered: created.length,
    skipped: skipped.length,
    skippedSample: skipped.slice(0, 12),
    drafts: drafts.length,
    creators: created,
    verified,
  };
}