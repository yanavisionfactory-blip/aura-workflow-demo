// Real provider execution for AURA workflow steps.
// Every successful return contains provider evidence. Unsupported or under-specified
// work throws, so the UI never reports an illustrated action as completed.

const json = async (response, label) => {
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!response.ok) {
    const detail = data?.error?.message || data?.error?.type || data?.message || text || "Unknown provider error";
    throw new Error(`${label} failed (${response.status}): ${String(detail).slice(0, 300)}`);
  }
  return data;
};

const authHeaders = (token) => ({ Authorization: `Bearer ${token}` });

function base64urlUtf8(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function extractGoogleId(value = "") {
  const match = String(value).match(/spreadsheets\/d\/([a-zA-Z0-9-_]+)/) ||
    String(value).match(/(?:spreadsheet(?:Id)?|sheet)[\s:=#-]+([a-zA-Z0-9-_]{20,})/i);
  return match?.[1] || "";
}

function rowsFromPreview(step) {
  const preview = step?.preview;
  if (!preview || preview.type !== "table" || !Array.isArray(preview.columns)) return [];
  return (preview.rows || []).map((row) =>
    Object.fromEntries(preview.columns.map((column, index) => [column, row?.[index] ?? ""]))
  );
}

export async function sendGmail(token, payload) {
  if (!payload.to) throw new Error("A recipient is required before Gmail can send");
  const email = [
    `To: ${payload.to}`,
    `Subject: ${payload.subject || "AURA workflow"}`,
    "Content-Type: text/plain; charset=utf-8",
    "MIME-Version: 1.0",
    "",
    payload.body || "",
  ].join("\r\n");
  const data = await json(await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
    method: "POST",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({ raw: base64urlUtf8(email) }),
  }), "Gmail send");
  return {
    output: `Email sent to ${payload.to} (message ${data.id})`,
    outcome: {
      type: "email", count: 1, title: "Email sent",
      detail: `Sent “${payload.subject || "AURA workflow"}” to ${payload.to}`,
      link: "https://mail.google.com/mail/u/0/#sent", linkLabel: "Open in Gmail",
      evidence: { provider: "gmail", message_id: data.id, thread_id: data.threadId },
    },
  };
}

export async function readGmail(token, intent) {
  const params = new URLSearchParams({ maxResults: String(Math.min(Number(intent.limit) || 10, 50)) });
  if (intent.query) params.set("q", intent.query);
  const list = await json(await fetch(`https://gmail.googleapis.com/gmail/v1/users/me/messages?${params}`, {
    headers: authHeaders(token),
  }), "Gmail read");
  const ids = (list.messages || []).slice(0, 10);
  const messages = await Promise.all(ids.map(async ({ id }) => {
    const data = await json(await fetch(
      `https://gmail.googleapis.com/gmail/v1/users/me/messages/${id}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date`,
      { headers: authHeaders(token) }
    ), "Gmail message");
    const headers = Object.fromEntries((data.payload?.headers || []).map((h) => [h.name.toLowerCase(), h.value]));
    return { id, threadId: data.threadId, subject: headers.subject || "(no subject)", from: headers.from || "", date: headers.date || "" };
  }));
  return {
    output: `Read ${messages.length} Gmail message${messages.length === 1 ? "" : "s"}`,
    outcome: {
      type: "message", count: messages.length, title: "Gmail messages read",
      detail: intent.query ? `${messages.length} matched “${intent.query}”` : `${messages.length} recent messages retrieved`,
      items: messages.map((m) => ({ label: m.subject, detail: m.from })),
      link: "https://mail.google.com/mail/u/0/#inbox", linkLabel: "Open Gmail",
      evidence: { provider: "gmail", message_ids: messages.map((m) => m.id), query: intent.query || "" },
    },
  };
}

async function airtableContext(token, intent = {}) {
  const bases = (await json(await fetch("https://api.airtable.com/v0/meta/bases", {
    headers: authHeaders(token),
  }), "Airtable bases")).bases || [];
  if (!bases.length) throw new Error("No Airtable bases are available to the connected account");
  const wantedBase = String(intent.base_id || intent.base_name || "").toLowerCase();
  const base = bases.find((b) => b.id === intent.base_id || b.name?.toLowerCase() === wantedBase) || bases[0];
  const tables = (await json(await fetch(`https://api.airtable.com/v0/meta/bases/${base.id}/tables`, {
    headers: authHeaders(token),
  }), "Airtable schema")).tables || [];
  if (!tables.length) throw new Error(`No tables found in Airtable base ${base.name}`);
  const wantedTable = String(intent.table_id || intent.table_name || "").toLowerCase();
  const table = tables.find((t) => t.id === intent.table_id || t.name?.toLowerCase() === wantedTable) || tables[0];
  return { base, table };
}

function coerceAirtableFields(table, raw) {
  const fields = {};
  const available = (table.fields || []).filter((f) => !["formula", "rollup", "count", "lookup", "createdTime", "lastModifiedTime", "autoNumber"].includes(f.type));
  for (const [key, value] of Object.entries(raw || {})) {
    const target = available.find((f) => f.name.toLowerCase() === key.toLowerCase());
    if (target) fields[target.name] = value;
  }
  if (!Object.keys(fields).length && available.length) {
    const firstValue = Object.values(raw || {})[0] ?? "Created by AURA";
    fields[available[0].name] = String(firstValue);
  }
  if (!Object.keys(fields).length) throw new Error("The selected Airtable table has no writable fields");
  return fields;
}

export async function createAirtable(token, intent, step) {
  const { base, table } = await airtableContext(token, intent);
  const previewRows = rowsFromPreview(step);
  const sourceRows = previewRows.length ? previewRows : [intent.fields || { Name: "Created by AURA" }];
  const records = sourceRows.slice(0, 10).map((fields) => ({ fields: coerceAirtableFields(table, fields) }));
  const data = await json(await fetch(`https://api.airtable.com/v0/${base.id}/${table.id}`, {
    method: "POST",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({ records, typecast: true }),
  }), "Airtable create");
  const recordIds = (data.records || []).map((r) => r.id);
  return {
    output: `Created ${recordIds.length} record${recordIds.length === 1 ? "" : "s"} in ${base.name} / ${table.name}`,
    outcome: {
      type: "document", count: recordIds.length, title: "Airtable records created",
      detail: `${recordIds.length} record${recordIds.length === 1 ? "" : "s"} added to ${table.name}`,
      link: `https://airtable.com/${base.id}/${table.id}`, linkLabel: "Open in Airtable",
      evidence: { provider: "airtable", base_id: base.id, table_id: table.id, record_ids: recordIds },
    },
  };
}

export async function readAirtable(token, intent) {
  const { base, table } = await airtableContext(token, intent);
  const params = new URLSearchParams({ maxRecords: String(Math.min(Number(intent.limit) || 20, 100)) });
  if (intent.query) params.set("filterByFormula", intent.query);
  const data = await json(await fetch(`https://api.airtable.com/v0/${base.id}/${table.id}?${params}`, {
    headers: authHeaders(token),
  }), "Airtable read");
  const records = data.records || [];
  return {
    output: `Read ${records.length} record${records.length === 1 ? "" : "s"} from ${base.name} / ${table.name}`,
    outcome: {
      type: "metric", count: records.length, title: "Airtable records read",
      detail: `${records.length} records retrieved from ${table.name}`,
      items: records.slice(0, 8).map((r) => ({ label: r.id, detail: JSON.stringify(r.fields).slice(0, 180) })),
      link: `https://airtable.com/${base.id}/${table.id}`, linkLabel: "Open in Airtable",
      evidence: { provider: "airtable", base_id: base.id, table_id: table.id, record_ids: records.map((r) => r.id) },
    },
  };
}

export async function readSheets(token, intent, contextText) {
  const spreadsheetId = intent.resource_id || extractGoogleId(contextText);
  if (!spreadsheetId) throw new Error("A Google Sheets URL or spreadsheet ID is required for this step");
  const range = intent.range || "A1:Z100";
  const data = await json(await fetch(
    `https://sheets.googleapis.com/v4/spreadsheets/${spreadsheetId}/values/${encodeURIComponent(range)}`,
    { headers: authHeaders(token) }
  ), "Google Sheets read");
  const values = data.values || [];
  return {
    output: `Read ${values.length} row${values.length === 1 ? "" : "s"} from ${data.range || range}`,
    outcome: {
      type: "document", count: values.length, title: "Sheet data read",
      detail: `${values.length} rows retrieved from ${data.range || range}`,
      items: values.slice(0, 8).map((row, i) => ({ label: `Row ${i + 1}`, detail: row.join(" · ").slice(0, 180) })),
      link: `https://docs.google.com/spreadsheets/d/${spreadsheetId}/edit`, linkLabel: "Open in Google Sheets",
      evidence: { provider: "googlesheets", spreadsheet_id: spreadsheetId, range: data.range || range, row_count: values.length },
    },
  };
}

export async function appendSheets(token, intent, step, contextText) {
  const spreadsheetId = intent.resource_id || extractGoogleId(contextText);
  if (!spreadsheetId) throw new Error("A Google Sheets URL or spreadsheet ID is required before rows can be written");
  const range = intent.range || "Sheet1!A1";
  const preview = step?.preview;
  const values = preview?.type === "table" && preview.columns
    ? [preview.columns, ...(preview.rows || [])]
    : (Array.isArray(intent.values) ? intent.values : []);
  if (!values.length) throw new Error("No approved rows were provided for the Google Sheets write");
  const data = await json(await fetch(
    `https://sheets.googleapis.com/v4/spreadsheets/${spreadsheetId}/values/${encodeURIComponent(range)}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`,
    {
      method: "POST",
      headers: { ...authHeaders(token), "Content-Type": "application/json" },
      body: JSON.stringify({ majorDimension: "ROWS", values }),
    }
  ), "Google Sheets append");
  return {
    output: `Appended ${data.updates?.updatedRows || values.length} row${values.length === 1 ? "" : "s"} to Google Sheets`,
    outcome: {
      type: "document", count: data.updates?.updatedRows || values.length, title: "Sheet rows added",
      detail: `Updated ${data.updates?.updatedRange || range}`,
      link: `https://docs.google.com/spreadsheets/d/${spreadsheetId}/edit`, linkLabel: "Open in Google Sheets",
      evidence: { provider: "googlesheets", spreadsheet_id: spreadsheetId, updated_range: data.updates?.updatedRange, updated_rows: data.updates?.updatedRows },
    },
  };
}

export async function readCalendar(token, intent) {
  const params = new URLSearchParams({
    maxResults: String(Math.min(Number(intent.limit) || 20, 100)),
    singleEvents: "true", orderBy: "startTime",
    timeMin: intent.time_min || new Date().toISOString(),
  });
  if (intent.time_max) params.set("timeMax", intent.time_max);
  if (intent.query) params.set("q", intent.query);
  const data = await json(await fetch(`https://www.googleapis.com/calendar/v3/calendars/primary/events?${params}`, {
    headers: authHeaders(token),
  }), "Google Calendar read");
  const events = data.items || [];
  return {
    output: `Read ${events.length} calendar event${events.length === 1 ? "" : "s"}`,
    outcome: {
      type: "message", count: events.length, title: "Calendar events read",
      detail: `${events.length} upcoming events retrieved`,
      items: events.slice(0, 8).map((e) => ({ label: e.summary || "(untitled)", detail: e.start?.dateTime || e.start?.date || "" })),
      link: "https://calendar.google.com/calendar/u/0/r", linkLabel: "Open Google Calendar",
      evidence: { provider: "googlecalendar", event_ids: events.map((e) => e.id) },
    },
  };
}

export async function createCalendarEvent(token, intent) {
  if (!intent.start) throw new Error("An event start time is required before Google Calendar can create it");
  const start = intent.start.includes("T") ? { dateTime: intent.start } : { date: intent.start };
  const endValue = intent.end || intent.start;
  const end = endValue.includes("T") ? { dateTime: endValue } : { date: endValue };
  const event = {
    summary: intent.title || intent.note || "AURA workflow event",
    description: intent.body || "",
    location: intent.location || "",
    start, end,
  };
  const data = await json(await fetch("https://www.googleapis.com/calendar/v3/calendars/primary/events", {
    method: "POST",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify(event),
  }), "Google Calendar create");
  return {
    output: `Created calendar event “${data.summary}”`,
    outcome: {
      type: "message", count: 1, title: "Calendar event created", detail: data.summary,
      link: data.htmlLink || "https://calendar.google.com/calendar/u/0/r", linkLabel: "Open event",
      evidence: { provider: "googlecalendar", event_id: data.id, html_link: data.htmlLink },
    },
  };
}

export async function executeToolIntent({ intent, step, tokens, prompt, interpretation, user }) {
  const tool = intent.tool || step.tool;
  const context = [prompt, interpretation, step.action, step.detail, JSON.stringify(step.flow || [])].join("\n");
  switch (intent.action_type) {
    case "send_email":
      if (!tokens.Gmail) throw new Error("Gmail is not connected");
      return sendGmail(tokens.Gmail, {
        to: step.preview?.type === "email" ? step.preview.to : (intent.to || user.email),
        subject: step.preview?.type === "email" ? step.preview.subject : intent.subject,
        body: step.preview?.type === "email" ? step.preview.body : intent.body,
      });
    case "read_email":
      if (!tokens.Gmail) throw new Error("Gmail is not connected");
      return readGmail(tokens.Gmail, intent);
    case "airtable_create":
      if (!tokens.Airtable) throw new Error("Airtable is not connected");
      return createAirtable(tokens.Airtable, intent, step);
    case "airtable_read":
      if (!tokens.Airtable) throw new Error("Airtable is not connected");
      return readAirtable(tokens.Airtable, intent);
    case "sheets_read":
      if (!tokens["Google Sheets"]) throw new Error("Google Sheets is not connected");
      return readSheets(tokens["Google Sheets"], intent, context);
    case "sheets_append":
      if (!tokens["Google Sheets"]) throw new Error("Google Sheets is not connected");
      return appendSheets(tokens["Google Sheets"], intent, step, context);
    case "calendar_read":
      if (!tokens["Google Calendar"]) throw new Error("Google Calendar is not connected");
      return readCalendar(tokens["Google Calendar"], intent);
    case "calendar_create":
      if (!tokens["Google Calendar"]) throw new Error("Google Calendar is not connected");
      return createCalendarEvent(tokens["Google Calendar"], intent);
    default:
      throw new Error(`${tool || "This tool"} does not yet have an executable adapter`);
  }
}