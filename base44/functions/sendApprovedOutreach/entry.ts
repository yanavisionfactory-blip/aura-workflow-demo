import { createClientFromRequest } from "npm:@base44/sdk@0.8.40";
import { secrets } from "base44:runtime";

// Sends first-outreach emails to creators the manager has APPROVED in AURA.
// Runs on a schedule. For each approved creator with a draft that hasn't been
// emailed yet, sends the draft via Gmail and marks the creator "emailed".
// Creators are never emailed until the manager explicitly approves them.

function base64urlUtf8(str) {
  const b64 = btoa(unescape(encodeURIComponent(str)));
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sendGmail(token, { to, subject, body }) {
  const email = [`To: ${to}`, `Subject: ${subject}`, "Content-Type: text/plain; charset=utf-8", "MIME-Version: 1.0", "", body].join("\r\n");
  const r = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ raw: base64urlUtf8(email) }),
  });
  if (!r.ok) {
    const t = await r.text().catch(() => "");
    throw new Error(`Gmail send failed (${r.status}): ${t.slice(0, 200)}`);
  }
  return { ok: true };
}

export default async function (req) {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });
    if (user.role !== "admin") return Response.json({ error: "Forbidden" }, { status: 403 });

    const gmailConn = await base44.asServiceRole.connectors.getConnection("gmail");
    const gmailToken = gmailConn?.accessToken;
    if (!gmailToken) return Response.json({ error: "Gmail not connected" }, { status: 400 });

    const managerEmail = secrets.get("GRAIL_TALENT_EMAIL");

    // Only creators the manager has explicitly approved, with a draft, not yet emailed.
    const approved = await base44.asServiceRole.entities.Creator.filter({ status: "approved" }, "-created_date", 200);
    const toEmail = (approved || []).filter((c) => c.email && c.outreach_subject && c.outreach_draft);
    if (!toEmail.length) return Response.json({ sent: 0, message: "No approved creators with drafts pending." });

    const sent = [];
    const failed = [];
    for (const c of toEmail) {
      try {
        await sendGmail(gmailToken, { to: c.email, subject: c.outreach_subject, body: c.outreach_draft });
        await base44.asServiceRole.entities.Creator.update(c.id, { status: "emailed" });
        sent.push(c.tiktok_username);
      } catch (e) {
        failed.push({ username: c.tiktok_username, error: e.message });
      }
    }

    // Notify the manager of what was sent.
    if (managerEmail && sent.length) {
      try {
        await sendGmail(gmailToken, {
          to: managerEmail,
          subject: `AURA: sent outreach to ${sent.length} creator${sent.length === 1 ? "" : "s"}`,
          body: `Hi,

AURA just sent first-outreach emails to ${sent.length} approved creator${sent.length === 1 ? "" : "s"}:

${sent.map((u) => "• " + u).join("\n")}
${failed.length ? `\nFailed (${failed.length}):\n${failed.map((f) => "• " + f.username + " — " + f.error).join("\n")}\n` : ""}
— AURA`,
        });
      } catch {}
    }

    return Response.json({ sent: sent.length, failed: failed.length, sentTo: sent, failedList: failed });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}