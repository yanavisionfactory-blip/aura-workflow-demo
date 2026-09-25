import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Eye, Mail, Database, ArrowLeft, Play, List, FileDown, FileText, Pencil, ListChecks, Check, ChevronDown, Plus, Trash2, Paperclip, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { aura } from "@/api/auraClient";
import { downloadEmailEml, safeName } from "@/lib/auraDownload";
import { applyPresentationCopy, dynamicReferences, presentationCopySchema } from "@/lib/canvaCopyEdit.mjs";
import { applyEmailCopy, emailCopySchema } from "@/lib/emailCopyEdit.mjs";
import { fallbackReviewContract, mergeLegacyPreviewIntoArguments, setArgumentAtPath, validateReviewArguments } from "@/lib/approvalReview.mjs";
import { editJiraBatchTask, jiraBatchTasks, removeJiraBatchTask } from "@/lib/jiraBatchReview.mjs";

function EditableEmail({ preview, onPreviewChange, onCopyChange = null, editing, artifacts = [], args = { subject: "", body: "" }, contract = null }) {
  const [instruction, setInstruction] = useState("");
  const [applying, setApplying] = useState(false);
  const [editError, setEditError] = useState("");
  const applyInstruction = async () => {
    if (!instruction.trim() || applying) return;
    setApplying(true);
    setEditError("");
    try {
      const suggestion = await aura.integrations.Core.InvokeLLM({
        prompt: "Revise only the subject and message of this email according to the user's request. Keep every {{...}} reference exactly intact; those values come from earlier steps. Do not change the recipient, attachments, or claim the email was sent. Return subject and body as JSON.\nCurrent email: "
          + JSON.stringify({ subject: args.subject || "", body: args.body || "" })
          + "\nUser request: " + instruction.trim(),
        response_json_schema: emailCopySchema,
      });
      const revised = applyEmailCopy(args, suggestion);
      const errors = validateReviewArguments(contract, revised);
      if (errors.length) throw new Error(errors[0].message);
      onCopyChange(revised);
      setInstruction("");
    } catch (error) {
      setEditError(error.message || "AURA could not apply that change. You can edit the email directly.");
    } finally {
      setApplying(false);
    }
  };
  return (
    <div className="overflow-hidden">
      <div className="flex items-center justify-between pb-3 text-xs text-muted-foreground">
        <span>Review the email</span>
        <button
          onClick={() => downloadEmailEml(`aura-email-${safeName(preview.subject)}.eml`, preview)}
          className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:border-white/20"
        >
          <FileDown className="w-3 h-3" /> Download draft
        </button>
      </div>
      <div className="space-y-3 text-sm">
        <div className="flex gap-3 items-center">
          <span className="w-20 flex-shrink-0 text-muted-foreground">To</span>
          <input
            value={String(preview.to || "").toLowerCase() === "me" || dynamicReferences(preview.to).length ? "" : preview.to || ""}
            placeholder={String(preview.to || "").toLowerCase() === "me" || dynamicReferences(preview.to).length ? "Your connected Gmail address" : "Recipient email"}
            onChange={(e) => onPreviewChange({ to: e.target.value })}
            readOnly={!editing}
            className={`min-w-0 flex-1 bg-transparent border-b py-1 outline-none ${editing ? "border-white/10 focus:border-primary" : "border-transparent"}`}
          />
        </div>
        <div className="flex gap-3 items-center">
          <span className="w-20 flex-shrink-0 text-muted-foreground">Subject</span>
          <input
            value={dynamicReferences(preview.subject).length ? "" : preview.subject || ""}
            placeholder={dynamicReferences(preview.subject).length ? "Filled from the completed steps" : "Subject"}
            onChange={(e) => onPreviewChange({ subject: e.target.value })}
            readOnly={!editing}
            className={`min-w-0 flex-1 bg-transparent border-b py-1 font-medium outline-none ${editing ? "border-white/10 focus:border-primary" : "border-transparent"}`}
          />
        </div>
        <div className="grid gap-3 pt-2 sm:grid-cols-[5rem_1fr]">
          <span className="text-muted-foreground">Message</span>
          <textarea
            value={dynamicReferences(preview.body).length ? "" : preview.body || ""}
            placeholder={dynamicReferences(preview.body).length ? "Filled from the completed steps" : "Write your message"}
            onChange={(e) => onPreviewChange({ body: e.target.value })}
            readOnly={!editing}
            rows={4}
            className="w-full resize-y border-0 bg-transparent font-sans text-sm leading-relaxed text-foreground outline-none"
          />
        </div>
        {artifacts.length > 0 && (
          <div className="space-y-1.5 border-t border-white/5 pt-3">
            <p className="text-xs text-muted-foreground">Attachments · added after approval</p>
            {artifacts.map((artifact, index) => (
              <div key={`${artifact.name}-${index}`} className="flex items-center gap-2 rounded-lg border border-white/6 bg-white/[0.02] px-3 py-2">
                <Paperclip className="h-3.5 w-3.5 flex-shrink-0 text-primary" />
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">{artifact.name}</p>
                  <p className="text-[10px] text-muted-foreground/60">{artifact.source || "Prepared by AURA"}</p>
                </div>
                <span className="ml-auto text-[10px] text-emerald-300/80">Attached after approval</span>
              </div>
            ))}
          </div>
        )}
        {preview.note && <p className="text-[11px] text-muted-foreground/60 italic pt-1">{preview.note}</p>}
        {editing && onCopyChange && <div className="border-t border-white/10 pt-4">
          <label htmlFor="aura-email-instruction" className="flex items-center gap-2 text-sm font-medium"><Sparkles className="h-4 w-4 text-primary" /> Tell AURA what to change in this email</label>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row">
            <textarea id="aura-email-instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={2} placeholder="For example: Make the message warmer and shorter." className="min-w-0 flex-1 resize-y rounded-xl border border-white/10 bg-white/[0.03] p-3 text-sm outline-none focus:border-primary" />
            <button type="button" disabled={applying || !instruction.trim()} onClick={applyInstruction} className="rounded-xl bg-primary px-5 py-3 text-sm font-medium text-primary-foreground disabled:opacity-50">{applying ? "Applying…" : "Apply with AURA"}</button>
          </div>
          {editError && <p role="alert" className="mt-2 text-xs text-rose-300">{editError}</p>}
        </div>}
      </div>
    </div>
  );
}

function ApprovalTable({ preview }) {
  return (
    <div className="rounded-xl border border-white/8 bg-card/40 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/6 bg-card/30">
        <Database className="w-3.5 h-3.5 text-accent" />
        <span className="text-xs font-medium">{preview.title}</span>
        {preview.rows && <span className="text-[10px] text-muted-foreground/50 ml-auto">{preview.rows.length} rows</span>}
      </div>
      <div className="overflow-x-auto max-h-72 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0">
            <tr className="border-b border-white/5 bg-card/60">
              {preview.columns.map((c) => (<th key={c} className="text-left font-medium text-muted-foreground/60 px-4 py-2 whitespace-nowrap">{c}</th>))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, i) => (
              <tr key={i} className="border-b border-white/[0.03] last:border-0 hover:bg-white/[0.02]">
                {row.map((cell, j) => (<td key={j} className="px-4 py-2 whitespace-nowrap">{cell}</td>))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {preview.previewNote && <p className="text-[11px] text-muted-foreground/60 px-4 py-2 border-t border-white/5">{preview.previewNote}</p>}
    </div>
  );
}

function ApprovalList({ preview }) {
  return (
    <div className="rounded-xl border border-white/8 bg-card/40 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/6 bg-card/30">
        <List className="w-3.5 h-3.5 text-accent" />
        <span className="text-xs font-medium">{preview.title}</span>
        {preview.items && <span className="text-[10px] text-muted-foreground/50 ml-auto">{preview.items.length} items</span>}
      </div>
      <div className="p-3 space-y-1.5 max-h-72 overflow-y-auto">
        {preview.items.map((it, i) => (
          <div key={i} className="flex items-start justify-between gap-3 p-1.5 rounded-md hover:bg-white/[0.02]">
            <span className="text-sm">{it.label}</span>
            <span className="text-xs text-muted-foreground text-right">{it.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function EditableJiraTask({ preview, onPreviewChange, editing }) {
  const dynamic = new Set(preview.dynamicFields || []);
  const fields = [
    { key: "project", label: "Project" },
    { key: "summary", label: "Task" },
    { key: "assignee", label: "Assignee" },
  ];
  return (
    <div className="rounded-xl border border-white/8 bg-card/40 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/6 bg-card/30">
        <ListChecks className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-medium">{preview.title || "Jira task preview"}</span>
        <span className="ml-auto flex items-center gap-1 text-[10px] text-emerald-300/80">
          <Check className="w-3 h-3" /> Prepared from your notes
        </span>
      </div>
      <div className="p-4 space-y-3">
        {fields.map(({ key, label }) => (
          <div key={key} className="grid grid-cols-[5rem_1fr] gap-3 items-start text-xs">
            <span className="text-muted-foreground/55 pt-1">{label}</span>
            <div>
              <input
                value={preview[key] || ""}
                onChange={(event) => onPreviewChange({ [key]: event.target.value })}
                readOnly={!editing || dynamic.has(key)}
                className={`w-full bg-transparent border-b outline-none py-1 ${editing && !dynamic.has(key) ? "border-white/10 focus:border-primary" : "border-transparent"}`}
              />
              {dynamic.has(key) && <p className="text-[10px] text-muted-foreground/45 mt-0.5">Filled automatically</p>}
            </div>
          </div>
        ))}
        <div className="grid grid-cols-[5rem_1fr] gap-3 items-start text-xs pt-1 border-t border-white/5">
          <span className="text-muted-foreground/55 pt-2">Details</span>
          <div>
            <textarea
              value={preview.description || ""}
              onChange={(event) => onPreviewChange({ description: event.target.value })}
              readOnly={!editing || dynamic.has("description")}
              rows={3}
              className={`w-full bg-transparent outline-none py-1.5 resize-y border-b ${editing && !dynamic.has("description") ? "border-white/10 focus:border-primary" : "border-transparent"}`}
            />
            {dynamic.has("description") && <p className="text-[10px] text-muted-foreground/45">Filled automatically</p>}
          </div>
        </div>
        {preview.note && <p className="text-[11px] text-muted-foreground/60 pt-1">{preview.note}</p>}
      </div>
    </div>
  );
}

function JiraBatchReview({ args, editing, onArgumentsChange }) {
  const ready = Array.isArray(args.source_blocks);
  const tasks = jiraBatchTasks(args);
  const [draftTitles, setDraftTitles] = useState({});
  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-card/40">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 bg-card/30 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <ListChecks className="h-4 w-4 text-primary" /> Jira tasks
        </div>
        {ready && <span className="text-xs text-muted-foreground">{tasks.length} {tasks.length === 1 ? "task" : "tasks"}</span>}
      </div>
      {!ready ? (
        <p className="p-4 text-sm leading-relaxed text-muted-foreground">
          AURA will read your Notion notes first. You can review the actual Jira tasks before any are created.
        </p>
      ) : tasks.length === 0 ? (
        <p className="p-4 text-sm leading-relaxed text-amber-200">
          No to-do or list items were found in these notes. Choose different notes before creating tasks.
        </p>
      ) : (
        <div className="divide-y divide-white/5">
          {tasks.map((task, position) => (
            <div key={task.index} className="flex items-start gap-3 px-4 py-3">
              <span className="mt-1 flex h-6 w-6 flex-none items-center justify-center rounded-lg bg-primary/15 text-xs text-primary">{position + 1}</span>
              {editing ? (
                <input
                  aria-label={`Jira task ${position + 1}`}
                  value={draftTitles[task.index] ?? task.title}
                  maxLength={255}
                  onChange={(event) => {
                    const title = event.target.value;
                    setDraftTitles((current) => ({ ...current, [task.index]: title }));
                    if (title.trim()) onArgumentsChange(editJiraBatchTask(args, task.index, title));
                  }}
                  onBlur={() => setDraftTitles((current) => {
                    const next = { ...current };
                    delete next[task.index];
                    return next;
                  })}
                  className="min-w-0 flex-1 border-b border-white/10 bg-transparent py-1 text-sm outline-none focus:border-primary"
                />
              ) : <p className="min-w-0 flex-1 py-1 text-sm">{task.title}</p>}
              {editing && <button type="button" aria-label={`Remove Jira task ${position + 1}`} onClick={() => { setDraftTitles({}); onArgumentsChange(removeJiraBatchTask(args, task.index)); }} className="rounded-lg p-1 text-muted-foreground hover:bg-white/5 hover:text-rose-300"><Trash2 className="h-4 w-4" /></button>}
            </div>
          ))}
        </div>
      )}
      <div className="border-t border-white/10 px-4 py-3">
        <label className="mb-2 block text-xs font-medium text-muted-foreground">Jira project</label>
        <input
          aria-label="Jira project"
          value={args.project_key || ""}
          placeholder="Use my only Jira project"
          readOnly={!editing}
          onChange={(event) => onArgumentsChange({ ...args, project_key: event.target.value })}
          className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 text-sm outline-none focus:border-primary"
        />
        {!args.project_key && <p className="mt-2 text-xs text-muted-foreground">If you have more than one Jira project, enter the short project key before creating tasks.</p>}
      </div>
    </div>
  );
}

function EditableDocument({ preview, onPreviewChange, editing }) {
  return (
    <div className="rounded-xl border border-white/8 bg-card/40 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/6 bg-card/30">
        <FileText className="w-3.5 h-3.5 text-accent" />
        <span className="text-xs font-medium">Document</span>
        <button
          onClick={() => downloadEmailEml(`aura-doc-${safeName(preview.docTitle || "draft")}.eml`, { to: "", subject: preview.docTitle || "", body: preview.docBody || "" })}
          className="ml-auto flex items-center gap-1 text-[10px] px-2 py-1 rounded-full border border-white/10 text-muted-foreground hover:text-foreground hover:border-white/20 transition-colors"
        >
          <FileDown className="w-3 h-3" /> .eml
        </button>
      </div>
      <div className="p-4 space-y-2">
        <div className="flex gap-2 items-center text-xs">
          <span className="text-muted-foreground/50 w-16 flex-shrink-0">Title</span>
          <input
            value={preview.docTitle || ""}
            onChange={(e) => onPreviewChange({ docTitle: e.target.value })}
            readOnly={!editing}
            className={`flex-1 bg-transparent border-b outline-none py-1 font-medium ${editing ? "border-white/10 focus:border-primary" : "border-transparent"}`}
          />
        </div>
        <div className="pt-2 mt-1 border-t border-white/5">
          <textarea
            value={preview.docBody || ""}
            onChange={(e) => onPreviewChange({ docBody: e.target.value })}
            readOnly={!editing}
            rows={10}
            className="w-full bg-transparent outline-none text-xs font-sans text-muted-foreground leading-relaxed resize-y border-0"
          />
        </div>
        {preview.note && <p className="text-[11px] text-muted-foreground/60 italic pt-1">{preview.note}</p>}
      </div>
    </div>
  );
}

const serializedValue = (value) => JSON.stringify(value ?? null, null, 2);

function JsonArgumentField({ field, value, editing, onChange, onValidityChange }) {
  const serialized = serializedValue(value);
  const [draft, setDraft] = useState(serialized);
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(serialized);
    setError("");
    onValidityChange(true);
  }, [field.key, serialized]);

  if (!editing || field.editable === false) {
    return (
      <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/5 bg-black/10 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
        {serialized}
      </pre>
    );
  }

  return (
    <div>
      <textarea
        value={draft}
        rows={Math.min(12, Math.max(4, draft.split("\n").length))}
        onChange={(event) => {
          const nextDraft = event.target.value;
          setDraft(nextDraft);
          try {
            const parsed = JSON.parse(nextDraft);
            setError("");
            onValidityChange(true);
            onChange(parsed);
          } catch {
            setError("Keep this as valid structured data before approving.");
            onValidityChange(false);
          }
        }}
        className={`w-full resize-y rounded-lg border bg-black/10 px-3 py-2 font-mono text-[11px] leading-relaxed outline-none ${error ? "border-rose-400/50" : "border-white/10 focus:border-primary"}`}
      />
      {error && <p className="mt-1 text-[10px] text-rose-300">{error}</p>}
    </div>
  );
}

function SchemaArgumentsEditor({ contract, args, editing, onArgumentsChange, onFieldValidity, excludeKeys = [] }) {
  const excluded = new Set(excludeKeys);
  const fields = (contract.fields || []).filter((field) => (
    !excluded.has(field.key)
    && (editing || field.required || Object.hasOwn(args || {}, field.key))
  ));
  if (!fields.length) return null;

  return (
    <div className="rounded-xl border border-white/8 bg-card/40 overflow-hidden">
      <div className="flex items-center gap-2 border-b border-white/6 bg-card/30 px-4 py-2.5">
        <Database className="h-3.5 w-3.5 text-accent" />
        <span className="text-xs font-medium">Additional details</span>
      </div>
      <div className="space-y-3 p-4">
        {fields.map((field) => {
          const value = args?.[field.key];
          const editable = editing && field.editable !== false;
          return (
            <label key={field.key} className="block">
              <span className="mb-1.5 flex items-center gap-1 text-[11px] text-muted-foreground">
                {field.label || field.key}
                {field.required && <span className="text-amber-300">required</span>}
              </span>
              {field.control === "json" ? (
                <JsonArgumentField
                  field={field}
                  value={value}
                  editing={editable}
                  onValidityChange={(valid) => onFieldValidity(field.key, valid)}
                  onChange={(next) => onArgumentsChange(setArgumentAtPath(args, field.path || [field.key], next))}
                />
              ) : field.control === "checkbox" ? (
                <div className="flex items-center gap-2 rounded-lg border border-white/5 px-3 py-2 text-xs">
                  <input
                    type="checkbox"
                    checked={Boolean(value)}
                    disabled={!editable}
                    onChange={(event) => onArgumentsChange(setArgumentAtPath(args, field.path || [field.key], event.target.checked))}
                    className="accent-primary"
                  />
                  <span>{value ? "Enabled" : "Disabled"}</span>
                </div>
              ) : field.control === "select" ? (
                <select
                  value={value ?? ""}
                  disabled={!editable}
                  onChange={(event) => onArgumentsChange(setArgumentAtPath(args, field.path || [field.key], event.target.value))}
                  className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 text-xs outline-none focus:border-primary disabled:opacity-70"
                >
                  {(field.options || []).map((option) => <option key={String(option)} value={option}>{String(option)}</option>)}
                </select>
              ) : field.control === "textarea" ? (
                <textarea
                  value={value ?? ""}
                  readOnly={!editable}
                  rows={5}
                  onChange={(event) => onArgumentsChange(setArgumentAtPath(args, field.path || [field.key], event.target.value))}
                  className={`w-full resize-y rounded-lg border bg-transparent px-3 py-2 text-xs leading-relaxed outline-none ${editable ? "border-white/10 focus:border-primary" : "border-white/5 text-muted-foreground"}`}
                />
              ) : (
                <input
                  type={field.control === "number" ? "number" : field.format === "email" ? "email" : "text"}
                  value={value ?? ""}
                  readOnly={!editable}
                  min={field.minimum}
                  max={field.maximum}
                  onChange={(event) => {
                    const next = field.control === "number" && event.target.value !== ""
                      ? Number(event.target.value)
                      : event.target.value;
                    onArgumentsChange(setArgumentAtPath(args, field.path || [field.key], next));
                  }}
                  className={`w-full rounded-lg border bg-transparent px-3 py-2 text-xs outline-none ${editable ? "border-white/10 focus:border-primary" : "border-white/5 text-muted-foreground"}`}
                />
              )}
              {field.description && <span className="mt-1 block text-[10px] leading-relaxed text-muted-foreground/55">{field.description}</span>}
            </label>
          );
        })}
      </div>
    </div>
  );
}

function EditablePresentation({ args, contract, editing, onArgumentsChange }) {
  const phases = Array.isArray(args.phases) ? args.phases : [];
  const [selectedSlide, setSelectedSlide] = useState(0);
  const [instruction, setInstruction] = useState("");
  const [applying, setApplying] = useState(false);
  const [editError, setEditError] = useState("");
  const activeIndex = Math.min(selectedSlide, Math.max(0, phases.length - 1));
  const activeSlide = phases[activeIndex] || { period: "", title: args.title || "Untitled design", items: [] };
  const sceneNames = { rain_window: "Rain at the window", paper_boat: "Paper boat", lantern: "Lantern" };
  const phaseLimit = contract.fields?.find((field) => field.key === "phases")?.max_items || 4;
  const displayValue = (value) => dynamicReferences(value).length ? String(value || "").replace(/\{\{[^}]+\}\}/g, "live information") : value || "";
  const editableValue = (value) => dynamicReferences(value).length ? "" : value || "";
  const inputStyle = editing ? "rounded-sm outline-none hover:ring-1 hover:ring-[#6085bb]/50 focus:ring-2 focus:ring-[#6085bb]" : "outline-none";
  const updatePhase = (index, patch) => {
    onArgumentsChange({ ...args, phases: phases.map((phase, i) => i === index ? { ...phase, ...patch } : phase) });
  };
  const applyInstruction = async () => {
    if (!instruction.trim() || applying) return;
    setApplying(true);
    setEditError("");
    try {
      const suggestion = await aura.integrations.Core.InvokeLLM({
        prompt: "Revise only the wording of this presentation according to the user's instruction. Keep the same number and order of slides. Keep every {{...}} reference exactly intact; those values come from earlier steps. Never invent an external action or claim Canva has been edited. Return the full title, subtitle and all slides with period, title and items as JSON.\nCurrent content: "
          + JSON.stringify({ title: args.title || "", subtitle: args.subtitle || "", slides: phases.map(({ period, title, items }) => ({ period, title, items })) })
          + "\nUser instruction: " + instruction.trim(),
        response_json_schema: presentationCopySchema,
      });
      const revised = applyPresentationCopy(args, suggestion);
      const errors = validateReviewArguments(contract, revised);
      if (errors.length) throw new Error(errors[0].message);
      onArgumentsChange(revised);
      setInstruction("");
    } catch (error) {
      setEditError(error.message || "AURA could not apply that change. Please edit the slide directly.");
    } finally {
      setApplying(false);
    }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 px-5 py-3">
        <span className="rounded-xl border border-primary/40 bg-primary/10 px-3 py-2 text-xs text-primary">AURA preview</span>
        <span className="text-xs text-muted-foreground">{editing ? "Click the slide to edit its text" : "A preview of what will be created after approval"}</span>
      </div>
      <div className="flex min-h-[320px] bg-[#20222e] sm:min-h-[430px]">
        {phases.length > 1 && (
          <nav aria-label="Presentation slides" className="hidden w-44 shrink-0 flex-col gap-2 border-r border-white/10 bg-[#222431] p-3 sm:flex">
            <span className="px-1 pb-2 text-sm font-medium">Slides</span>
            {phases.map((phase, index) => (
              <button key={index} type="button" onClick={() => setSelectedSlide(index)}
                aria-current={activeIndex === index ? "true" : undefined}
                className={activeIndex === index ? "rounded-xl border border-primary bg-primary/15 p-2 text-left text-xs" : "rounded-xl border border-white/10 bg-white/5 p-2 text-left text-xs hover:border-white/25"}>
                <span className="block truncate text-muted-foreground">{index + 1} · {displayValue(phase.period) || "Slide"}</span>
                <span className="mt-1 block truncate">{displayValue(phase.title) || "Untitled slide"}</span>
              </button>
            ))}
          </nav>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between gap-2 border-b border-white/10 px-4 py-3 text-xs">
            <input aria-label="Presentation title" value={editableValue(args.title)} placeholder={dynamicReferences(args.title).length ? displayValue(args.title) : "Presentation title"} onChange={(event) => onArgumentsChange({ ...args, title: event.target.value })} readOnly={!editing} className={`min-w-0 flex-1 truncate border-0 bg-transparent font-medium text-foreground ${inputStyle}`} />
            <span className="shrink-0 text-muted-foreground">{phases.length || 1} {phases.length === 1 ? "slide" : "slides"}</span>
          </div>
          <div className="flex flex-1 items-center justify-center p-3 sm:p-6">
            <div className="relative aspect-video w-full max-w-3xl overflow-hidden bg-[#f1f7ff] p-5 text-[#1e2b3d] shadow-xl sm:p-9">
              <div aria-hidden="true" className="absolute -right-[12%] -top-[34%] h-[92%] w-[42%] rounded-full bg-[#c5def8]" />
              <div className="relative flex h-full flex-col">
                <input aria-label={`Slide ${activeIndex + 1} label`} value={editableValue(activeSlide.period)} placeholder={dynamicReferences(activeSlide.period).length ? displayValue(activeSlide.period) : "SLIDE LABEL"} onChange={(event) => updatePhase(activeIndex, { period: event.target.value })} readOnly={!editing} className={`w-[80%] border-0 bg-transparent text-[10px] font-semibold uppercase tracking-[.18em] text-[#42638c] sm:text-xs ${inputStyle}`} />
                <textarea aria-label={`Slide ${activeIndex + 1} title`} value={editableValue(activeSlide.title)} placeholder={dynamicReferences(activeSlide.title).length ? displayValue(activeSlide.title) : "Slide heading"} onChange={(event) => updatePhase(activeIndex, { title: event.target.value })} readOnly={!editing} rows={2} className={`mt-4 w-[80%] resize-none border-0 bg-transparent text-xl font-semibold leading-tight text-[#172238] sm:mt-6 sm:text-3xl ${inputStyle}`} />
                <textarea aria-label="Presentation subtitle" value={editableValue(args.subtitle)} placeholder={dynamicReferences(args.subtitle).length ? displayValue(args.subtitle) : "Add a subtitle"} onChange={(event) => onArgumentsChange({ ...args, subtitle: event.target.value })} readOnly={!editing} rows={2} className={`mt-2 w-[80%] resize-none border-0 bg-transparent text-xs text-[#4b607a] sm:text-sm ${inputStyle}`} />
                <div className="mt-4 max-h-[30%] space-y-1 overflow-y-auto text-xs text-[#364d67] sm:mt-7 sm:text-sm">
                  {(activeSlide.items || []).map((item, index) => <div key={index} className="flex items-center gap-2">
                    <input aria-label={`Slide ${activeIndex + 1} line ${index + 1}`} value={editableValue(item)} placeholder={dynamicReferences(item).length ? displayValue(item) : "Add text"} onChange={(event) => updatePhase(activeIndex, { items: activeSlide.items.map((line, i) => i === index ? event.target.value : line) })} readOnly={!editing} className={`min-w-0 w-[86%] border-0 bg-transparent text-[#364d67] ${inputStyle}`} />
                    {editing && activeSlide.items.length > 1 && <button type="button" aria-label={`Remove line ${index + 1}`} onClick={() => updatePhase(activeIndex, { items: activeSlide.items.filter((_, i) => i !== index) })} className="text-[#647997] hover:text-rose-500"><Trash2 className="h-3 w-3" /></button>}
                  </div>)}
                  {editing && (activeSlide.items || []).length < 5 && <button type="button" onClick={() => updatePhase(activeIndex, { items: [...(activeSlide.items || []), ""] })} className="text-[10px] text-[#42638c] hover:underline">+ Add text</button>}
                </div>
                {args.layout === "slides" && <div className="mt-auto flex items-center gap-2 text-[10px] text-[#647997]">
                  <span>Illustration</span>
                  <select aria-label={`Slide ${activeIndex + 1} illustration`} value={activeSlide.scene || ""} onChange={(event) => updatePhase(activeIndex, { scene: event.target.value || undefined })} disabled={!editing} className="max-w-[65%] rounded bg-white/80 px-1 py-0.5 text-[#42638c] outline-none disabled:opacity-70">
                    <option value="">Text only</option>
                    {Object.entries(sceneNames).map(([scene, label]) => <option key={scene} value={scene}>{label}</option>)}
                  </select>
                </div>}
              </div>
            </div>
          </div>
          {phases.length > 1 && (
            <div className="flex gap-2 overflow-x-auto border-t border-white/10 px-3 py-3 sm:hidden">
              {phases.map((phase, index) => (
                <button type="button" key={index} onClick={() => setSelectedSlide(index)}
                  className={activeIndex === index ? "shrink-0 rounded-lg bg-primary px-3 py-2 text-xs text-primary-foreground" : "shrink-0 rounded-lg bg-white/10 px-3 py-2 text-xs"}>
                  {index + 1} · {displayValue(phase.title) || "Slide"}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      {editing && (
        <div className="border-t border-white/10 px-5 py-3">
          <div className="flex flex-wrap gap-3">
            {phases.length > 1 && <button type="button" onClick={() => { onArgumentsChange({ ...args, phases: phases.filter((_, index) => index !== activeIndex) }); setSelectedSlide(Math.max(0, activeIndex - 1)); }} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-rose-300"><Trash2 className="h-3.5 w-3.5" /> Remove slide</button>}
            {phases.length < phaseLimit && <button type="button" onClick={() => { onArgumentsChange({ ...args, phases: [...phases, { period: `Slide ${phases.length + 1}`, title: "New slide", items: ["Add text"] }] }); setSelectedSlide(phases.length); }} className="inline-flex items-center gap-1 text-xs text-primary"><Plus className="h-3.5 w-3.5" /> Add slide</button>}
          </div>
        </div>
      )}
      {editing && phases.length > 0 && <div className="border-t border-white/10 px-5 py-5">
        <label htmlFor="aura-presentation-instruction" className="flex items-center gap-2 text-sm font-medium"><Sparkles className="h-4 w-4 text-primary" /> Tell AURA what to change in the text</label>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          <textarea id="aura-presentation-instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={2} placeholder="For example: Make slide 2 shorter and friendlier." className="min-w-0 flex-1 resize-y rounded-xl border border-white/10 bg-white/[0.03] p-3 text-sm outline-none focus:border-primary" />
          <button type="button" disabled={applying || !instruction.trim()} onClick={applyInstruction} className="rounded-xl bg-primary px-5 py-3 text-sm font-medium text-primary-foreground disabled:opacity-50">{applying ? "Applying…" : "Apply with AURA"}</button>
        </div>
        {editError && <p role="alert" className="mt-2 text-xs text-rose-300">{editError}</p>}
        <p className="mt-2 text-xs text-muted-foreground">Changes here update this preview. The design will be created in Canva after you approve.</p>
      </div>}
    </div>
  );
}

function FallbackPreview({ step }) {
  const f = step.flow || [];
  return (
    <div className="rounded-xl border border-white/8 bg-card/40 p-4 space-y-3">
      {step.output && (
        <div>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground/50">Will produce</span>
          <p className="text-sm mt-0.5">{step.output}</p>
        </div>
      )}
      <div className={step.output ? "pt-2 border-t border-white/5" : ""}>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground/50">What you are approving</span>
        <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
          AURA will prepare the final values from the completed steps before making this change.
        </p>
      </div>
      {f.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {f.map((fl, i) => (
            <span key={i} className="text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
              {fl.label}: {fl.value}
            </span>
          ))}
        </div>
      )}
      {!step.output && !step.detail && f.length === 0 && (
        <p className="text-xs text-muted-foreground">No preview available.</p>
      )}
    </div>
  );
}

const parseArguments = (step) => {
  if (step.arguments && typeof step.arguments === "object") return step.arguments;
  try {
    const parsed = JSON.parse(step.detail || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
};

const friendlyValue = (value, kind) => {
  if (value == null || value === "") return kind === "to" ? "Your connected Gmail address" : "Filled automatically by AURA";
  if (String(value).toLowerCase() === "me") return "Your connected Gmail address";
  if (/\{\{[^}]+\}\}/.test(String(value))) {
    if (kind === "to") return "Your connected Gmail address";
    if (kind === "subject") return "Prepared automatically from your request";
    if (kind === "body") return "Prepared automatically from the completed steps";
    return "Filled automatically by AURA";
  }
  return String(value);
};

const previewForStep = (step) => {
  if (step.preview?.type) return step.preview;
  const args = parseArguments(step);
  const identity = `${step.tool || ""} ${step.action || ""} ${step.title || ""}`.toLowerCase();
  if (identity.includes("gmail") || identity.includes("email")) {
    return {
      type: "email",
      to: friendlyValue(args.to, "to"),
      subject: friendlyValue(args.subject, "subject"),
      body: friendlyValue(args.body, "body"),
      sourceValues: { to: args.to, subject: args.subject, body: args.body },
      note: "AURA fills the forecast into the message before sending it.",
    };
  }
  return null;
};

function EditableStepCard({ step, number, index, onUpdate, onFieldValidity }) {
  const p = previewForStep(step) || {};
  const isModify = step.riskLevel === "modify";
  const args = step.resolvedArguments || step.arguments || {};
  const contract = step.reviewContract || fallbackReviewContract(
    step.operation || step.action || "app.action",
    args,
    step.tool || "App",
  );
  const richEmail = contract.operation === "gmail.send";
  const richTicket = contract.operation === "jira.issue.create";
  const richJiraBatch = contract.operation === "jira.issues.create_from_blocks";
  const richPresentation = contract.operation === "canva.presentation.create";
  const richDocument = contract.kind === "document";
  const [editing, setEditing] = useState(() => richEmail || richPresentation || richDocument || richJiraBatch);
  const updateArguments = (nextArguments) => onUpdate(index, {
    arguments: nextArguments,
    resolvedArguments: nextArguments,
  });
  const updatePreview = (patch) => {
    const nextPreview = { ...p, ...patch };
    const nextArguments = richEmail ? { ...args, ...patch } : mergeLegacyPreviewIntoArguments(step, nextPreview);
    onUpdate(index, {
      preview: nextPreview,
      arguments: nextArguments,
      resolvedArguments: nextArguments,
    });
  };
  const updateEmailCopy = (nextArguments) => onUpdate(index, {
    preview: { ...p, subject: nextArguments.subject, body: nextArguments.body },
    arguments: nextArguments,
    resolvedArguments: nextArguments,
  });
  const fieldValidity = (fieldKey, valid) => onFieldValidity(`${index}:${fieldKey}`, valid);

  if (!isModify) return null;

  // Modify step (sends / changes data): the focus of review — expanded & editable.
  return (
    <div className="overflow-hidden rounded-[22px] border border-white/15 bg-[#121827]">
      <div className="flex items-start gap-3 px-5 py-5 sm:gap-4">
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-primary/15 text-sm text-primary">
          {number}
        </div>
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-violet-600 text-xs font-medium text-white">
          {richPresentation ? "Canva" : richEmail ? <Mail className="h-5 w-5" /> : richDocument ? <FileText className="h-5 w-5" /> : (step.tool || "App").slice(0, 1)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-base font-medium text-foreground">{richPresentation ? args.title || step.action || contract.title : step.action || contract.title}</p>
              <p className="mt-1 text-sm text-muted-foreground">{richPresentation ? `${Array.isArray(args.phases) ? args.phases.length : 1}-slide presentation` : step.tool} · needs your review</p>
            </div>
            <button type="button" onClick={() => setEditing((e) => !e)}
              className="flex items-center gap-1 rounded-lg border border-white/10 px-3 py-2 text-xs text-muted-foreground hover:border-primary/50 hover:text-primary">
              <Pencil className="h-3.5 w-3.5" /> {editing ? "Editing" : "Edit in AURA"}
            </button>
          </div>
          {step.riskNote && <p className="mt-2 text-xs text-amber-200">{step.riskNote}</p>}
        </div>
      </div>
      <div className={richPresentation ? "border-t border-white/10" : "border-t border-white/10 p-5"}>
        {step.reviewContract ? (
          <>
            {richEmail && <EditableEmail preview={p} onPreviewChange={updatePreview} onCopyChange={updateEmailCopy} args={args} contract={contract} editing={editing} artifacts={contract.artifacts || (Array.isArray(args.attachments) ? args.attachments.map((attachment) => ({ name: attachment.filename || "Attachment", source: "From this workflow" })) : [])} />}
            {richTicket && <EditableJiraTask preview={p} onPreviewChange={updatePreview} editing={editing} />}
            {richJiraBatch && <JiraBatchReview args={args} editing={editing} onArgumentsChange={updateArguments} />}
            {richDocument && <EditableDocument preview={p} onPreviewChange={updatePreview} editing={editing} />}
            {richPresentation && (
              <EditablePresentation
                args={args}
                contract={contract}
                editing={editing}
                onArgumentsChange={updateArguments}
              />
            )}
            {!richPresentation && !richDocument && !richEmail && (
              <SchemaArgumentsEditor
                contract={contract}
                args={args}
                editing={editing}
                onArgumentsChange={updateArguments}
                onFieldValidity={fieldValidity}
                excludeKeys={richTicket
                    ? ["project_key", "projectKey", "project", "summary", "description", "assignee_id", "assignee"]
                    : richJiraBatch ? ["source_blocks", "project_key", "project_query"] : []}
              />
            )}
          </>
        ) : p.type === "email" ? <EditableEmail preview={p} onPreviewChange={updatePreview} editing={editing} />
          : p.type === "jira" ? <EditableJiraTask preview={p} onPreviewChange={updatePreview} editing={editing} />
          : p.type === "document" ? <EditableDocument preview={p} onPreviewChange={updatePreview} editing={editing} />
          : p.type === "table" ? <ApprovalTable preview={p} />
          : p.type === "list" ? <ApprovalList preview={p} />
          : <FallbackPreview step={step} />}
      </div>
    </div>
  );
}

export default function PreviewView({ preview, steps, onApprove, onBack, error = "" }) {
  const initial = steps && steps.length ? steps : preview?.steps || [];
  const [editSteps, setEditSteps] = useState(() => JSON.parse(JSON.stringify(initial)));
  const [showBackground, setShowBackground] = useState(false);
  const [invalidFields, setInvalidFields] = useState(() => new Set());
  if (!editSteps.length) return null;

  const update = (i, patch) => setEditSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  const updateFieldValidity = (key, valid) => setInvalidFields((previous) => {
    const next = new Set(previous);
    if (valid) next.delete(key);
    else next.add(key);
    return next;
  });
  const reviewSteps = editSteps
    .map((step, index) => ({ step, index }))
    .filter(({ step }) => step.riskLevel === "modify");
  const backgroundSteps = editSteps
    .map((step, index) => ({ step, index }))
    .filter(({ step }) => step.riskLevel !== "modify");
  const contractErrors = reviewSteps.flatMap(({ step, index }) => (
    step.reviewContract
      ? validateReviewArguments(step.reviewContract, step.resolvedArguments || step.arguments || {})
        .map((error) => ({ ...error, stepIndex: index }))
      : []
  ));
  const emptyJiraBatch = reviewSteps.some(({ step }) => {
    const args = step.resolvedArguments || step.arguments || {};
    return step.operation === "jira.issues.create_from_blocks"
      && Array.isArray(args.source_blocks) && jiraBatchTasks(args).length === 0;
  });
  const jiraTasksPending = reviewSteps.length === 1
    && reviewSteps[0].step.operation === "jira.issues.create_from_blocks"
    && !Array.isArray((reviewSteps[0].step.resolvedArguments || reviewSteps[0].step.arguments || {}).source_blocks);
  const approvalBlocked = invalidFields.size > 0 || contractErrors.length > 0 || emptyJiraBatch;
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.4 }}
      className="mx-auto w-full max-w-5xl"
    >
      {/* Header */}
      <div className="mb-2 flex items-center gap-4">
        <div className="rounded-2xl bg-violet-500/15 p-3">
          <Eye className="h-5 w-5 text-violet-300" />
        </div>
        <div>
          <h2 className="text-2xl font-semibold text-foreground">Review before running</h2>
          <p className="mt-1 text-sm text-muted-foreground">Check what AURA is about to create or send. You can edit each action before approving.</p>
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3 text-sm">
        <span className="rounded-full bg-violet-500/15 px-4 py-2 text-violet-200">{reviewSteps.length} {reviewSteps.length === 1 ? "change needs" : "changes need"} approval</span>
        <span className="text-muted-foreground">Nothing will be created or sent until you approve.</span>
      </div>

      {backgroundSteps.length > 0 && (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setShowBackground((value) => !value)}
            className="flex w-full items-center justify-between rounded-xl border border-sky-400/15 bg-sky-400/[0.04] px-4 py-3 text-xs text-sky-300 hover:bg-sky-400/[0.08]"
          >
            <span>{showBackground ? "Hide preparation steps" : `Show ${backgroundSteps.length} preparation ${backgroundSteps.length === 1 ? "step" : "steps"}`}</span>
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showBackground ? "rotate-180" : ""}`} />
          </button>
          {showBackground && (
            <div className="mt-2 space-y-1.5 rounded-xl border border-white/6 bg-card/20 p-3">
              {backgroundSteps.map(({ step, index }) => (
                <div key={index} className="flex items-start gap-2 text-xs">
                  <Check className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-sky-400" />
                  <div><span className="text-muted-foreground/60">{step.tool}</span><p className="text-foreground/80">{step.title || step.action}</p></div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Editable steps */}
      <div className="mb-6 mt-5 space-y-4">
        {reviewSteps.map(({ step, index }, reviewIndex) => (
          <EditableStepCard key={index} step={step} number={reviewIndex + 1} index={index} onUpdate={update} onFieldValidity={updateFieldValidity} />
        ))}
      </div>

      {contractErrors.length > 0 && (
        <div className="mb-4 rounded-xl border border-rose-400/20 bg-rose-400/5 px-4 py-3 text-[11px] text-rose-200">
          Complete the highlighted approval values before running. {contractErrors[0].message}
        </div>
      )}

      {emptyJiraBatch && <p className="mb-4 text-xs text-amber-200">There are no Jira tasks to create. Return to the plan and choose notes with action items.</p>}

      {error && (
        <div className="mb-4 rounded-xl border border-rose-400/20 bg-rose-400/5 px-4 py-3 text-[11px] leading-relaxed text-rose-200">
          {error}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between gap-3 border-t border-white/10 pt-5">
        <Button variant="ghost" size="sm" onClick={onBack} className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
          Back to plan
        </Button>
        <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
          <Button
            size="sm"
            disabled={approvalBlocked}
            onClick={() => onApprove(editSteps.map((step) => ({
              ...step,
              preview: previewForStep(step) || step.preview,
            })))}
            className="gap-1.5 border-0 bg-gradient-to-r from-violet-500 to-violet-600 text-white hover:from-violet-600 hover:to-violet-700"
          >
            <Play className="w-3.5 h-3.5" />
            {approvalBlocked ? "Complete required values" : jiraTasksPending ? "Read notes & preview tasks" : "Approve & run"}
          </Button>
        </motion.div>
      </div>
    </motion.div>
  );
}
