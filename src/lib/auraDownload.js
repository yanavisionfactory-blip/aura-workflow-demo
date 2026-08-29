// Download helpers for AURA artifacts (CSV, .eml, plain text).

function triggerDownload(filename, mime, content) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  const s = String(value ?? "");
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function safeName(s) {
  return (s || "aura").replace(/[^\w]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase();
}

export function downloadCSV(filename, headers, rows) {
  const lines = [headers.map(csvCell).join(",")];
  rows.forEach((r) => lines.push(r.map(csvCell).join(",")));
  triggerDownload(filename, "text/csv;charset=utf-8", lines.join("\n"));
}

export function downloadEmailEml(filename, { to, subject, body }) {
  const date = new Date().toUTCString();
  const eml = [
    `To: ${to}`,
    `Subject: ${subject}`,
    `Date: ${date}`,
    `From: AURA <aura@app.com>`,
    `MIME-Version: 1.0`,
    `Content-Type: text/plain; charset=utf-8`,
    ``,
    body,
  ].join("\n");
  triggerDownload(filename, "message/rfc822", eml);
}

export function downloadTextFile(filename, content) {
  triggerDownload(filename, "text/plain;charset=utf-8", content);
}

export { safeName };