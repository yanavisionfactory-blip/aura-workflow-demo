import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Eye, Mail, Database, ArrowLeft, Play, List, FileDown, FileText, Pencil, ListChecks, Check, ChevronDown, Plus, Trash2, Paperclip, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { aura } from "@/api/auraClient";
import { downloadEmailEml, safeName } from "@/lib/auraDownload";
import { applyPresentationCopy, presentationCopySchema } from "@/lib/canvaCopyEdit.mjs";
import { fallbackReviewContract, mergeLegacyPreviewIntoArguments, setArgumentAtPath, validateReviewArguments } from "@/lib/approvalReview.mjs";

function EditableEmail({ preview, onPreviewChange, editing, artifacts = [] }) {
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
            value={String(preview.to || "").toLowerCase() === "me" ? "" : preview.to || ""}
            placeholder={String(preview.to || "").toLowerCase() === "me" ? "Your connected Gmail address" : "Recipient email"}
            onChange={(e) => onPreviewChange({ to: e.target.value })}
            readOnly={!editing}
            className={`min-w-0 flex-1 bg-transparent border-b py-1 outline-none ${editing ? "border-white/10 focus:border-primary" : "border-transparent"}`}
          />
        </div>
        <div className="flex gap-3 items-center">
          <span className="w-20 flex-shrink-0 text-muted-foreground">Subject</span>
          <input
            value={preview.subject || ""}
            onChange={(e) => onPreviewChange({ subject: e.target.value })}
            readOnly={!editing}
            className={`min-w-0 flex-1 bg-transparent border-b py-1 font-medium outline-none ${editing ? "border-white/10 focus:border-primary" : "border-transparent"}`}
          />
        </div>
        <div className="grid gap-3 pt-2 sm:grid-cols-[5rem_1fr]">
          <span className="text-muted-foreground">Message</span>
          <textarea
            value={preview.body || ""}
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

function EditablePresentation({ args, contract, editing, onArgumentsChange, onFieldValidity }) {
  const phases = Array.isArray(args.phases) ? args.phases : [];
  const [selectedSlide, setSelectedSlide] = useState(0);
  const [instruction, setInstruction] = useState("");
  const [applying, setApplying] = useState(false);
  const [editError, setEditError] = useState("");
  const activeIndex = Math.min(selectedSlide, Math.max(0, phases.length - 1));
  const activeSlide = phases[activeIndex] || { period: "", title: args.title || "Untitled design", items: [] };
  const sceneNames = { rain_window: "Rain at the window", paper_boat: "Paper boat", lantern: "Lantern" };
  const phaseLimit = contract.fields?.find((field) => field.key === "phases")?.max_items || 4;
  const updatePhase = (index, patch) => {
    onArgumentsChange({ ...args, phases: phases.map((phase, i) => i === index ? { ...phase, ...patch } : phase) });
  };
  const applyInstruction = async () => {
    if (!instruction.trim() || applying) return;
    setApplying(true);
    setEditError("");
    try {
      const suggestion = await aura.integrations.Core.InvokeLLM({
        prompt: "Revise only the wording of this presentation according to the user's instruction. Keep the same number and order of slides. Never invent an external action or claim Canva has been edited. Return the full title, subtitle and all slides with period, title and items as JSON.\nCurrent content: "
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
        <span className="text-xs text-muted-foreground">A preview of what will be created after approval</span>
      </div>
      <div className="flex min-h-[320px] bg-[#20222e] sm:min-h-[430px]">
        {phases.length > 1 && (
          <nav aria-label="Presentation slides" className="hidden w-44 shrink-0 flex-col gap-2 border-r border-white/10 bg-[#222431] p-3 sm:flex">
            <span className="px-1 pb-2 text-sm font-medium">Slides</span>
            {phases.map((phase, index) => (
              <button key={index} type="button" onClick={() => setSelectedSlide(index)}
                aria-current={activeIndex === index ? "true" : undefined}
                className={activeIndex === index ? "rounded-xl border border-primary bg-primary/15 p-2 text-left text-xs" : "rounded-xl border border-white/10 bg-white/5 p-2 text-left text-xs hover:border-white/25"}>
                <span className="block truncate text-muted-foreground">{index + 1} · {phase.period || "Slide"}</span>
                <span className="mt-1 block truncate">{phase.title || "Untitled slide"}</span>
              </button>
            ))}
          </nav>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between gap-2 border-b border-white/10 px-4 py-3 text-xs">
            <span className="truncate font-medium">{args.title || "Untitled presentation"}</span>
            <span className="shrink-0 text-muted-foreground">{phases.length || 1} {phases.length === 1 ? "slide" : "slides"}</span>
          </div>
          <div className="flex flex-1 items-center justify-center p-3 sm:p-6">
            <div className="relative aspect-video w-full max-w-3xl overflow-hidden bg-[#f1f7ff] p-5 text-[#1e2b3d] shadow-xl sm:p-9">
              <div aria-hidden="true" className="absolute -right-[12%] -top-[34%] h-[92%] w-[42%] rounded-full bg-[#c5def8]" />
              <div className="relative flex h-full flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-[.18em] text-[#42638c] sm:text-xs">{activeSlide.period || "YOUR STORY"}</span>
                <h3 className="mt-4 max-w-[80%] break-words text-xl font-semibold leading-tight text-[#172238] sm:mt-6 sm:text-3xl">{activeSlide.title || args.title || "Untitled slide"}</h3>
                <p className="mt-2 max-w-[80%] break-words text-xs text-[#4b607a] sm:text-sm">{args.subtitle}</p>
                <div className="mt-4 space-y-1 text-xs text-[#364d67] sm:mt-7 sm:text-sm">
                  {(activeSlide.items || []).slice(0, 4).map((item, index) => <p key={index} className="max-w-[86%] break-words">{item}</p>)}
                </div>
                {activeSlide.scene && <span className="mt-auto text-[10px] text-[#647997]">Illustration: {sceneNames[activeSlide.scene] || activeSlide.scene}</span>}
              </div>
            </div>
          </div>
          {phases.length > 1 && (
            <div className="flex gap-2 overflow-x-auto border-t border-white/10 px-3 py-3 sm:hidden">
              {phases.map((phase, index) => (
                <button type="button" key={index} onClick={() => setSelectedSlide(index)}
                  className={activeIndex === index ? "shrink-0 rounded-lg bg-primary px-3 py-2 text-xs text-primary-foreground" : "shrink-0 rounded-lg bg-white/10 px-3 py-2 text-xs"}>
                  {index + 1} · {phase.title || "Slide"}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      {editing && (
        <div className="space-y-4 border-t border-white/10 px-5 py-5">
          <p className="text-sm font-medium">Edit this design</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-muted-foreground">Presentation title
              <input aria-label="Presentation title" value={args.title || ""} onChange={(event) => onArgumentsChange({ ...args, title: event.target.value })} className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-foreground outline-none focus:border-primary" />
            </label>
            <label className="text-xs text-muted-foreground">Subtitle
              <input aria-label="Presentation subtitle" value={args.subtitle || ""} onChange={(event) => onArgumentsChange({ ...args, subtitle: event.target.value })} className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-foreground outline-none focus:border-primary" />
            </label>
            {phases.length > 0 && <>
              <label className="text-xs text-muted-foreground">Slide {activeIndex + 1} heading
                <input aria-label={"Phase " + (activeIndex + 1) + " title"} value={activeSlide.title || ""} onChange={(event) => updatePhase(activeIndex, { title: event.target.value })} className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-foreground outline-none focus:border-primary" />
              </label>
              <label className="text-xs text-muted-foreground">Slide {activeIndex + 1} label
                <input aria-label={"Phase " + (activeIndex + 1) + " period"} value={activeSlide.period || ""} onChange={(event) => updatePhase(activeIndex, { period: event.target.value })} className="mt-1 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-foreground outline-none focus:border-primary" />
              </label>
              <label className="text-xs text-muted-foreground sm:col-span-2">Slide {activeIndex + 1} text · one line per point
                <textarea aria-label={"Phase " + (activeIndex + 1) + " items"} value={(activeSlide.items || []).join("\n")} rows={3} onChange={(event) => updatePhase(activeIndex, { items: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })} className="mt-1 w-full resize-y rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-foreground outline-none focus:border-primary" />
              </label>
              {args.layout === "slides" && <label className="text-xs text-muted-foreground">Slide {activeIndex + 1} illustration
                <select aria-label={"Phase " + (activeIndex + 1) + " illustration"} value={activeSlide.scene || ""} onChange={(event) => updatePhase(activeIndex, { scene: event.target.value || undefined })} className="mt-1 w-full rounded-lg border border-white/10 bg-[#20222e] px-3 py-2 text-sm text-foreground outline-none focus:border-primary">
                  <option value="">Text only</option>
                  {Object.entries(sceneNames).map(([scene, label]) => <option key={scene} value={scene}>{label}</option>)}
                </select>
              </label>}
            </>}
          </div>
          <div className="flex flex-wrap gap-3">
            {phases.length > 1 && <button type="button" onClick={() => { onArgumentsChange({ ...args, phases: phases.filter((_, index) => index !== activeIndex) }); setSelectedSlide(Math.max(0, activeIndex - 1)); }} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-rose-300"><Trash2 className="h-3.5 w-3.5" /> Remove slide</button>}
            {phases.length < phaseLimit && <button type="button" onClick={() => { onArgumentsChange({ ...args, phases: [...phases, { period: "", title: "", items: [""] }] }); setSelectedSlide(phases.length); }} className="inline-flex items-center gap-1 text-xs text-primary"><Plus className="h-3.5 w-3.5" /> Add slide</button>}
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
      <div className="px-5 pb-5"><SchemaArgumentsEditor contract={contract} args={args} editing={editing} onArgumentsChange={onArgumentsChange} onFieldValidity={onFieldValidity} excludeKeys={["title", "subtitle", "phases"]} /></div>
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
  const richPresentation = contract.operation === "canva.presentation.create";
  const richDocument = contract.kind === "document";
  const [editing, setEditing] = useState(() => richEmail || richPresentation || richDocument);
  const updateArguments = (nextArguments) => onUpdate(index, {
    arguments: nextArguments,
    resolvedArguments: nextArguments,
  });
  const updatePreview = (patch) => {
    const nextPreview = { ...p, ...patch };
    onUpdate(index, {
      preview: nextPreview,
      arguments: mergeLegacyPreviewIntoArguments(step, nextPreview),
      resolvedArguments: mergeLegacyPreviewIntoArguments(step, nextPreview),
    });
  };
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
            {richEmail && <EditableEmail preview={p} onPreviewChange={updatePreview} editing={editing} artifacts={contract.artifacts || (Array.isArray(args.attachments) ? args.attachments.map((attachment) => ({ name: attachment.filename || "Attachment", source: "From this workflow" })) : [])} />}
            {richTicket && <EditableJiraTask preview={p} onPreviewChange={updatePreview} editing={editing} />}
            {richDocument && <EditableDocument preview={p} onPreviewChange={updatePreview} editing={editing} />}
            {richPresentation && (
              <EditablePresentation
                args={args}
                contract={contract}
                editing={editing}
                onArgumentsChange={updateArguments}
                onFieldValidity={fieldValidity}
              />
            )}
            {!richPresentation && !richDocument && (
              <SchemaArgumentsEditor
                contract={contract}
                args={args}
                editing={editing}
                onArgumentsChange={updateArguments}
                onFieldValidity={fieldValidity}
                excludeKeys={richEmail
                  ? ["to", "subject", "body", "attachments"]
                  : richTicket
                    ? ["project_key", "projectKey", "project", "summary", "description", "assignee_id", "assignee"]
                    : []}
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
  const approvalBlocked = invalidFields.size > 0 || contractErrors.length > 0;
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
            {approvalBlocked ? "Complete required values" : "Approve & run"}
          </Button>
        </motion.div>
      </div>
    </motion.div>
  );
}
