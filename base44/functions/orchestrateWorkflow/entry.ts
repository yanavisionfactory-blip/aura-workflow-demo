import { createClientFromRequest } from "npm:@base44/sdk@0.8.40";
import { secrets } from "base44:runtime";
import { TOOL_REGISTRY } from "../../shared/toolRegistry.ts";
import { isCreatorOutreachIntent, runCreatorOutreachCore } from "../../shared/creatorOutreach.ts";

// AURA's orchestrator. This is where the workflow actually runs.
//
// The frontend approved a plan (an array of steps). This function:
//   1. Asks the orchestrator model to turn each step into a concrete
//      execution intent (which real tool to call, what operation, what payload).
//   2. Executes each intent against the user's REAL connected tools:
//        - Gmail  -> sends a real email through the Gmail API
//        - Airtable -> creates a real record through the Airtable API
//      Tools that aren't connected are marked `needs_connection` (never faked).
//   3. Writes live per-step status into the WorkflowRun record as it goes, so
//      the frontend can show real progress by polling the run.
//   4. Compiles a results summary from the REAL outcomes (not invented).
//
// Nothing about routing or method selection is exposed to the user — the
// frontend only shows step progress and the final results.

const INTENT_SCHEMA = {
  type: "object",
  properties: {
    intents: {
      type: "array",
      items: {
        type: "object",
        properties: {
          action_type: {
            type: "string",
            enum: ["send_email", "create_record", "read_data", "other"],
          },
          tool: { type: "string" },
          to: { type: "string" },
          subject: { type: "string" },
          body: { type: "string" },
          fields: { type: "object", additionalProperties: true },
          note: { type: "string" },
        },
      },
    },
  },
};

const RESULTS_SCHEMA = {
  type: "object",
  properties: {
    title: { type: "string" },
    summary: { type: "string" },
    metrics: {
      type: "array",
      items: {
        type: "object",
        properties: { value: { type: "string" }, label: { type: "string" } },
      },
    },
    outcomes: {
      type: "array",
      items: {
        type: "object",
        properties: {
          type: { type: "string" },
          count: { type: "number" },
          title: { type: "string" },
          detail: { type: "string" },
          attention: { type: "boolean" },
          link: { type: "string" },
          linkLabel: { type: "string" },
        },
      },
    },
    nextSteps: { type: "array", items: { type: "string" } },
  },
};

function base64urlUtf8(str) {
  const b64 = btoa(unescape(encodeURIComponent(str)));
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sendGmail(token, { to, subject, body }) {
  const email = [
    `To: ${to}`,
    `Subject: ${subject}`,
    "Content-Type: text/plain; charset=utf-8",
    "MIME-Version: 1.0",
    "",
    body,
  ].join("\r\n");
  const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ raw: base64urlUtf8(email) }),
  });
  if (!r.ok) {
    const t = await r.text().catch(() => "");
    throw new Error(`Gmail send failed (${r.status}): ${t.slice(0, 200)}`);
  }
  const data = await r.json();
  return { messageId: data.id, to, subject };
}

async function airtableCreateRecord(token, fields) {
  // List bases, pick the first, list its tables, pick the first, create a record.
  const basesRes = await fetch("https://api.airtable.com/v0/meta/bases", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!basesRes.ok) throw new Error(`Airtable bases failed (${basesRes.status})`);
  const basesJson = await basesRes.json();
  const bases = basesJson.bases || [];
  if (!bases.length) throw new Error("No Airtable bases found");
  const baseId = bases[0].id;
  const schemaRes = await fetch(`https://api.airtable.com/v0/meta/bases/${baseId}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!schemaRes.ok) throw new Error(`Airtable schema failed (${schemaRes.status})`);
  const schemaJson = await schemaRes.json();
  const tables = schemaJson.tables || [];
  if (!tables.length) throw new Error("No Airtable tables found");
  const table = tables[0];
  const recRes = await fetch(`https://api.airtable.com/v0/${baseId}/${table.id}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ records: [{ fields: fields || { "Name": "AURA workflow result" } }] }),
  });
  if (!recRes.ok) {
    const t = await recRes.text().catch(() => "");
    throw new Error(`Airtable create failed (${recRes.status}): ${t.slice(0, 200)}`);
  }
  const recJson = await recRes.json();
  return { baseId, tableId: table.id, tableName: table.name, recordId: recJson.records?.[0]?.id };
}

// Build AURA results outcomes from the creator-outreach core's return.
function buildCreatorOutcomes(r) {
  const out = [];
  out.push({ type: "metric", title: "Creators discovered", detail: `${r.candidates} candidates found via ${r.verified ? "Modash (verified)" : "web search"}` });
  out.push({ type: "metric", title: "Qualifying creators", detail: `${r.qualifying} passed all 9 criteria + dedup` });
  if (!r.verified) {
    out.push({
      type: "alert",
      title: "Results are unverified",
      detail: "No creator-data API connected — stats and emails are LLM web-search estimates and may be wrong. Connect Modash for verified data.",
      attention: true,
    });
  }
  const pending = (r.creators || []).filter((c) => c.status === "discovered");
  if (pending.length) {
    out.push({
      type: "creators", count: pending.length, title: "Ready for your approval",
      detail: `${pending.length} creator${pending.length === 1 ? "" : "s"} found — approve them and AURA will send the outreach email`,
      items: pending.map((c) => ({ id: c.id, label: c.tiktok_username, detail: `${c.full_name || ""} — ${c.email}`, status: "discovered", subject: c.outreach_subject || "", body: c.outreach_draft || "" })),
    });
  }
  const withDrafts = (r.creators || []).filter((c) => c.outreach_subject);
  if (withDrafts.length) {
    out.push({
      type: "email", count: withDrafts.length, title: "Outreach drafts ready",
      detail: "First-outreach email drafts written in your Gmail voice — sent only after you approve",
      items: withDrafts.map((c) => ({ label: c.tiktok_username, detail: c.outreach_subject })),
    });
  }
  out.push({ type: "message", title: "Manager notified", detail: "Summary emailed to the Grail Talent manager" });
  if (r.skipped) out.push({ type: "metric", title: "Skipped", detail: `${r.skipped} candidates already contacted or didn't qualify` });
  return out;
}

async function compileResults(base44, outcomes, interpretation) {
  return await base44.asServiceRole.integrations.Core.InvokeLLM({
    prompt: `You are AURA. A workflow just finished executing for real. Summarize what actually happened, based ONLY on these real outcomes (do not invent actions that didn't run):

${outcomes.map((o) => `- [${o.type}] ${o.title}: ${o.detail}`).join("\n")}

Confirmed intent: ${interpretation}

Generate:
- "title": short outcome title (4-6 words).
- "summary": one sentence on what was accomplished.
- "metrics": 3 key numbers (value + label) derived from the outcomes (counts of emails sent, records created, reads, failures, etc.).
- "outcomes": the outcomes above, cleaned up (keep type/count/title/detail/link/linkLabel/attention).
- "nextSteps": 3 short follow-up suggestions.`,
    response_json_schema: RESULTS_SCHEMA,
  });
}

// Resolve a real access token for a tool via the shared OAuth connection
// (the builder authorizes the connector once — no client secrets, no per-user
// setup). Returns a real access token or null; never fakes one.
async function getToolToken(base44, entry) {
  if (entry.connector) {
    try {
      const conn = await base44.asServiceRole.connectors.getConnection(entry.connector);
      if (conn?.accessToken) return conn.accessToken;
    } catch {
      return null;
    }
  }
  return null;
}

export default async function (req) {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

    const body = await req.json().catch(() => ({}));
    const runId = body.runId;
    const steps = Array.isArray(body.steps) ? body.steps : [];
    const interpretation = body.interpretation || "";
    const prompt = body.prompt || "";

    if (!runId) return Response.json({ error: "runId is required" }, { status: 400 });
    if (!steps.length) return Response.json({ error: "steps is required" }, { status: 400 });

    // ---- 1. Orchestrator decides the execution intent for each step ----
    const intentRes = await base44.asServiceRole.integrations.Core.InvokeLLM({
      prompt: `You are AURA's orchestrator. Turn each workflow step into a concrete execution intent — what to actually DO when running it.

Confirmed intent: ${interpretation}
Original request: ${prompt}

Steps:
${steps.map((s, i) => `${i + 1}. ${s.tool}: ${s.action || s.iWill || ""}`).join("\n")}

For EACH step, return one intent object:
- "action_type": "send_email" if the step sends an email; "create_record" if it writes a row/record to a sheet or CRM; "read_data" if it only fetches/reads; "other" otherwise.
- "tool": the canonical tool name (exactly as given).
- For send_email: fill "to" (a realistic recipient address), "subject" (realistic subject line), "body" (a realistic, complete email body reflecting the step's purpose — not a placeholder).
- For create_record: fill "fields" (a JSON object of column name -> value, realistic content reflecting the step).
- "note": one short line describing what will happen.

Be concrete and realistic. These will be REALLY executed against the user's connected tools.`,
      response_json_schema: INTENT_SCHEMA,
    });
    const intents = intentRes.intents || [];

    // ---- 2. Resolve real connection tokens up front ----
    const tokens = {};
    for (const name of Object.keys(TOOL_REGISTRY)) {
      const entry = TOOL_REGISTRY[name];
      if (entry.method === "oauth") {
        const tok = await getToolToken(base44, entry);
        if (tok) tokens[name] = tok;
      }
    }

    // ---- 3. Execute each step against real tools, writing live status ----
    const execSteps = steps.map((s) => ({
      tool: s.tool,
      action: s.action || s.iWill || "",
      riskLevel: s.riskLevel || "read",
      status: "pending",
      output: "",
    }));
    await base44.entities.WorkflowRun.update(runId, { steps: execSteps }).catch(() => {});

    // ---- Creator outreach: delegate the whole job to the shared core ----
    if (isCreatorOutreachIntent(interpretation + " " + prompt)) {
      const phaseKeywords = {
        discovery: ["discover", "find", "search", "research", "identify", "scan"],
        dedup: ["dedup", "sheet", "contacted", "filter", "database", "skip", "existing"],
        submit: ["submit", "approver", "approval"],
        draft: ["draft", "outreach email", "email draft"],
        notify: ["notify", "summary", "report"],
      };
      const stepText = (s) => ((s.action || "") + " " + (s.iWill || "") + " " + (s.tool || "")).toLowerCase();
      // Each step is claimed by at most one phase — the first phase (in order)
      // whose keywords it matches. Later phases skip already-claimed steps.
      const claimed = new Set();
      const phaseStep = (phase) => {
        const kws = phaseKeywords[phase];
        for (let i = 0; i < steps.length; i++) {
          if (claimed.has(i)) continue;
          if (kws.some((k) => stepText(steps[i]).includes(k))) { claimed.add(i); return i; }
        }
        return -1;
      };
      // Resolve each phase -> step index ONCE, up front, so the live "running"
      // updates and the final "completed" updates target the same step.
      const phaseStepMap = {};
      for (const phase of Object.keys(phaseKeywords)) phaseStepMap[phase] = phaseStep(phase);

      const setStep = (i, patch) => { if (i >= 0 && i < execSteps.length) execSteps[i] = { ...execSteps[i], ...patch }; };
      const flush = () => base44.entities.WorkflowRun.update(runId, { steps: execSteps }).catch(() => {});

      const onPhase = (phase, detail) => {
        const i = phaseStepMap[phase];
        if (i >= 0) { setStep(i, { status: "running", output: `→ ${detail}` }); flush(); }
      };

      // Niche: prefer the user's edited discovery-step action, then the prompt.
      // The user can refine the niche on the preview screen — that edit must
      // drive the search.
      const extractNiche = (text) => {
        if (!text) return null;
        let m = text.match(/(?:in|for|on)\s+(?:the\s+)?([a-z][a-z ,'\-]+?)\s+niche/i);
        if (m) return m[1].trim();
        m = text.match(/creators?\s+(?:in|on|about)\s+([a-z][a-z ,'\-]+)/i);
        if (m) return m[1].trim();
        return null;
      };
      let niche = null;
      for (const s of steps) {
        niche = extractNiche((s.action || "") + " " + (s.iWill || ""));
        if (niche) break;
      }
      if (!niche) niche = extractNiche(prompt);

      // The user may have edited the sample outreach email on the preview
      // screen — pass it as a template so drafts match their wording.
      const emailTemplate = (() => {
        const p = steps.find((s) => s.preview && s.preview.type === "email")?.preview;
        if (!p || !(p.subject || p.body)) return null;
        return { to: p.to || "", subject: p.subject || "", body: p.body || "" };
      })();

      let outcomes;
      let stepStart = Date.now();
      try {
        const coreResult = await runCreatorOutreachCore(base44, secrets, { niche, maxCreators: 5, onPhase, emailTemplate });
        // complete each phase step with its outcome line
        const phaseDone = {
          discovery: `→ Found ${coreResult.candidates} candidates`,
          dedup: `→ ${coreResult.contactedInSheet} in Grail sheet, ${coreResult.qualifying} qualifying`,
          submit: `→ ${coreResult.discovered || 0} ready for your approval`,
          draft: `→ ${coreResult.drafts} outreach drafts written`,
          notify: "→ Manager emailed",
        };
        for (const phase of Object.keys(phaseKeywords)) {
          const i = phaseStepMap[phase];
          if (i >= 0) setStep(i, { status: "completed", output: phaseDone[phase], duration: `${((Date.now() - stepStart) / 1000).toFixed(1)}s` });
        }
        execSteps.forEach((s, i) => { if (s.status === "pending") setStep(i, { status: "completed", output: "→ Done" }); });
        await flush();
        outcomes = buildCreatorOutcomes(coreResult);
      } catch (e) {
        execSteps.forEach((s, i) => { if (s.status === "running" || s.status === "pending") setStep(i, { status: "failed", output: "→ Error: " + e.message }); });
        await flush();
        outcomes = [{ type: "alert", title: "Creator outreach failed", detail: e.message, attention: true }];
      }

      const realSummary = await compileResults(base44, outcomes, interpretation);
      const runUpdate = {
        status: "completed",
        title: realSummary.title,
        summary: realSummary.summary,
        metrics: realSummary.metrics,
        outcomes: realSummary.outcomes || outcomes,
        steps: execSteps,
        notes: outcomes.some((o) => o.attention) ? "Some submissions need manual follow-up." : "",
      };
      await base44.entities.WorkflowRun.update(runId, runUpdate).catch(() => {});
      return Response.json({ steps: execSteps, results: realSummary });
    }

    const outcomes = [];
    for (let i = 0; i < steps.length; i++) {
      const intent = intents[i] || { action_type: "other", tool: steps[i].tool };
      const stepStart = Date.now();

      execSteps[i] = { ...execSteps[i], status: "running" };
      await base44.entities.WorkflowRun.update(runId, { steps: execSteps }).catch(() => {});

      let status = "completed";
      let output = "";
      try {
        if (intent.action_type === "send_email" && tokens.Gmail) {
          // Prefer the user's edited preview content over the LLM intent —
          // edits on the preview screen drive execution.
          const pv = steps[i].preview && steps[i].preview.type === "email" ? steps[i].preview : null;
          const sent = await sendGmail(tokens.Gmail, {
            to: (pv && pv.to) || intent.to || user.email,
            subject: (pv && pv.subject) || intent.subject || "AURA workflow",
            body: (pv && pv.body) || intent.body || "",
          });
          output = `→ Email sent to ${sent.to} (subject: "${sent.subject}")`;
          outcomes.push({
            type: "email",
            count: 1,
            title: "Email sent",
            detail: `Sent "${sent.subject}" to ${sent.to}`,
            link: "https://mail.google.com/mail/u/0/#sent",
            linkLabel: "Open in Gmail",
          });
        } else if (intent.action_type === "create_record" && tokens.Airtable) {
          const rec = await airtableCreateRecord(tokens.Airtable, intent.fields || {});
          output = `→ Record created in Airtable (${rec.tableName})`;
          outcomes.push({
            type: "document",
            count: 1,
            title: "Record created",
            detail: `New record in ${rec.tableName}`,
            link: `https://airtable.com/${rec.baseId}`,
            linkLabel: "Open in Airtable",
          });
        } else if (intent.action_type === "read_data") {
          output = `→ ${intent.note || "Read data from " + intent.tool}`;
          outcomes.push({
            type: "metric",
            title: `${intent.tool} read`,
            detail: intent.note || "Data retrieved",
          });
        } else {
          // Tool isn't really connected (no token) — never fake it.
          status = "needs_connection";
          output = `→ ${intent.tool || steps[i].tool} is not connected — skipped`;
          outcomes.push({
            type: "alert",
            title: `${intent.tool || steps[i].tool} not connected`,
            detail: "This step needs a connected tool to run.",
            attention: true,
          });
        }
      } catch (e) {
        status = "failed";
        output = `→ Error: ${e.message}`;
        outcomes.push({
          type: "alert",
          title: `${steps[i].tool} step failed`,
          detail: e.message,
          attention: true,
        });
      }

      execSteps[i] = {
        ...execSteps[i],
        status,
        output,
        duration: `${((Date.now() - stepStart) / 1000).toFixed(1)}s`,
      };
      await base44.entities.WorkflowRun.update(runId, { steps: execSteps }).catch(() => {});
    }

    // ---- 4. Compile results from REAL outcomes ----
    const realSummary = await compileResults(base44, outcomes, interpretation);

    const finalSteps = execSteps.map((s) => ({ ...s }));
    const runUpdate = {
      status: "completed",
      title: realSummary.title,
      summary: realSummary.summary,
      metrics: realSummary.metrics,
      outcomes: realSummary.outcomes || outcomes,
      steps: finalSteps,
      notes: execSteps.some((s) => s.status === "needs_connection")
        ? "Some steps needed a connected tool that wasn't available."
        : "",
    };
    await base44.entities.WorkflowRun.update(runId, runUpdate).catch(() => {});

    return Response.json({
      steps: finalSteps,
      results: realSummary,
    });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}