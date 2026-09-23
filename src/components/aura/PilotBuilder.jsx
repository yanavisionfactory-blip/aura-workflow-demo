import { useState } from "react";
import { formatLocalTime, parseLocalTime } from "@/lib/pilotTime.mjs";

const PILOT_PREFIX = "AURA_PILOT_V1\n";

export default function PilotBuilder({ onSubmit, onBack, initialValues = null }) {
  const illustratedPoem = initialValues?.illustrated_poem === true;
  const [fields, setFields] = useState(() => ({
    doc_title: initialValues?.doc_title || "", doc_body: initialValues?.doc_body || "",
    event_title: initialValues?.event_title || "",
    event_start: formatLocalTime(initialValues?.event_start),
    event_end: formatLocalTime(initialValues?.event_end),
    canva_title: initialValues?.canva_title || "",
    canva_bullets: initialValues?.canva_bullets?.join("\n") || "",
  }));
  const [error, setError] = useState("");
  const update = (key) => (event) => setFields((current) => ({ ...current, [key]: event.target.value }));

  const submit = (event) => {
    event.preventDefault();
    const start = parseLocalTime(fields.event_start);
    const end = parseLocalTime(fields.event_end);
    const bullets = fields.canva_bullets.split("\n").map((item) => item.trim()).filter(Boolean);
    if (!start || !end || start <= new Date() || end <= start
        || end - start > 4 * 60 * 60 * 1000
        || end - new Date() > 30 * 24 * 60 * 60 * 1000) {
      setError("Enter a future event within 30 days as YYYY-MM-DD HH:mm, with start and end at most four hours apart.");
      return;
    }
    if (!fields.doc_body.trim() || bullets.length < 1 || bullets.length > 5
        || bullets.some((item) => item.length > 90)) {
      setError("Add document text and one to five slide bullets, each under 90 characters.");
      return;
    }
    setError("");
    onSubmit(PILOT_PREFIX + JSON.stringify({
      doc_title: fields.doc_title.trim(), doc_body: fields.doc_body.trim(),
      event_title: fields.event_title.trim(), event_start: start.toISOString(),
      event_end: end.toISOString(), canva_title: fields.canva_title.trim(),
      canva_bullets: bullets, email_to: "me", illustrated_poem: illustratedPoem,
    }));
  };

  const input = (key, label, type = "text", maxLength = 80) => (
    <label className="flex flex-col gap-1 text-sm text-foreground/80">
      {label}
      <input required type={type} maxLength={type === "text" ? maxLength : undefined}
        value={fields[key]} onChange={update(key)}
        className="rounded-lg border border-white/15 bg-card px-3 py-2 text-foreground" />
    </label>
  );

  return (
    <form onSubmit={submit} className="mx-auto max-w-2xl rounded-2xl border border-white/10 bg-card/80 p-5 space-y-4">
      <div>
        <h2 className="text-xl font-semibold">{illustratedPoem ? "Poem + illustrations pilot" : "Four-app pilot"}</h2>
        <p className="text-sm text-muted-foreground mt-1">
          {illustratedPoem
            ? "Review the poem and set tomorrow's presentation time. AURA will write it in Google Docs, make three illustrated pages in Canva, and email you the full poem with the illustrated PDF."
            : "Use your exact content and event time. AURA will create a Google Doc, a calendar event, a Canva slide, and email the PDF to your connected Gmail account."}
          {" "}You will review each external change.
        </p>
      </div>
      {input("doc_title", illustratedPoem ? "Poem title" : "Google Doc title")}
      <label className="flex flex-col gap-1 text-sm text-foreground/80">
        {illustratedPoem ? "Poem to write in Google Docs" : "Google Doc text"}
        <textarea required maxLength={4000} rows={4} value={fields.doc_body} onChange={update("doc_body")}
          className="rounded-lg border border-white/15 bg-card px-3 py-2 text-foreground" />
      </label>
      {input("event_title", "Presentation event title")}
      <div className="grid gap-3 sm:grid-cols-2">
        {input("event_start", "Start (your local time, YYYY-MM-DD HH:mm)", "text", 16)}
        {input("event_end", "End (your local time, YYYY-MM-DD HH:mm)", "text", 16)}
      </div>
      {input("canva_title", illustratedPoem ? "Illustrated Canva presentation title" : "Canva slide title", "text", 50)}
      {illustratedPoem ? (
        <p className="text-sm text-muted-foreground">Canva will contain three illustrations, one for each verse. The poem itself appears in the email alongside the illustrated PDF.</p>
      ) : (
        <label className="flex flex-col gap-1 text-sm text-foreground/80">
          Canva slide bullets (one per line)
          <textarea required rows={4} value={fields.canva_bullets} onChange={update("canva_bullets")}
            placeholder="One to five bullets, up to 90 characters each"
            className="rounded-lg border border-white/15 bg-card px-3 py-2 text-foreground" />
        </label>
      )}
      <p className="text-xs text-muted-foreground">Email destination: your connected Gmail account.</p>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      <div className="flex justify-end gap-3">
        <button type="button" onClick={onBack} className="rounded-lg border border-white/15 px-4 py-2 text-sm">Back</button>
        <button type="submit" className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">Review pilot plan</button>
      </div>
    </form>
  );
}
