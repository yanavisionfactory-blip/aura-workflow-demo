import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Eye, Mail, Database, ShieldAlert, ArrowLeft, Play, List, FileDown, FileText, Pencil, ListChecks, Check, ChevronDown, Presentation, Plus, Trash2, Paperclip, Sparkles, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { aura } from "@/api/auraClient";
import LiveToolReview from "@/components/aura/LiveToolReview";
import { downloadEmailEml, safeName } from "@/lib/auraDownload";
import { fallbackReviewContract, mergeLegacyPreviewIntoArguments, setArgumentAtPath, validateReviewArguments } from "@/lib/approvalReview.mjs";

const liveToolReviewEnabled = (
  import.meta.env.VITE_LIVE_TOOL_REVIEW_ENABLED === "true"
  && typeof window !== "undefined"
  && new URLSearchParams(window.location.search).get("liveToolReview") === "1"
);

const formatBytes = (value) => {
  if (!Number.isFinite(value) || value < 0) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
};

const schemaForValue = (value) => {
  if (Array.isArray(value)) {
    return { type: "array", items: value.length ? schemaForValue(value[0]) : { type: "string" } };
  }
  if (value && typeof value === "object") {
    const keys = Object.keys(value);
    return {
      type: "object",
      properties: Object.fromEntries(keys.map((key) => [key, schemaForValue(value[key])])),
      required: keys,
    };
  }
  if (typeof value === "boolean") return { type: "boolean" };
  if (typeof value === "number") return { type: Number.isInteger(value) ? "integer" : "number" };
  return { type: "string" };
};

function PromptApprovalEditor({ step, args, onArgumentsChange }) {
  const [instruction, setInstruction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    const request = instruction.trim();
    if (!request || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const response = await aura.integrations.Core.InvokeLLM({
        prompt: `Revise the prepared ${step.tool || "app"} action using the user's instruction.

Operation: ${step.operation || step.action}
Current user-facing values:
${JSON.stringify(args, null, 2)}

User instruction: ${request}

Return the complete revised arguments. Preserve every value the user did not ask to change. Do not add credentials, URLs, IDs, operations, or technical settings.`,
        response_json_schema: {
          type: "object",
          properties: { arguments: schemaForValue(args) },
          required: ["arguments"],
        },
      });
      if (!response?.arguments || typeof response.arguments !== "object") {
        throw new Error("AURA did not return an editable revision.");
      }
      onArgumentsChange({ ...args, ...response.arguments });
      setInstruction("");
    } catch (revisionError) {
      setError(revisionError?.message || "AURA couldn't apply that change.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="rounded-xl border border-primary/20 bg-primary/[0.04] p-3">
      <div className="mb-2 flex items-center gap-2">
        <Sparkles className="h-3.5 w-3.5 text-primary" />
        <span className="text-xs font-medium text-primary/90">Tell AURA what to change</span>
      </div>
      <div className="flex gap-2">
        <textarea
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          rows={2}
          placeholder="For example: make slide 2 clearer, use a warmer tone, or shorten the email."
          className="min-w-0 flex-1 resize-none rounded-lg border border-white/10 bg-card/70 px-3 py-2 text-xs leading-relaxed outline-none placeholder:text-muted-foreground/45 focus:border-primary/40"
        />
        <button
          type="button"
          onClick={submit}
          disabled={!instruction.trim() || submitting}
          className="self-stretch rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Apply"}
        </button>
      </div>
      {error && <p className="mt-2 text-[11px] text-rose-300">{error}</p>}
    </div>
  );
}

function EditableEmail({ preview, onPreviewChange, editing, artifacts = [] }) {
  return (
    <div className="rounded-xl border border-white/8 bg-card/40 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/6 bg-card/30">
        <Mail className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-medium">Email preview</span>
        <button
          onClick={() => downloadEmailEml(`aura-email-${safeName(preview.subject)}.eml`, preview)}
          className="ml-auto flex items-center gap-1 text-[10px] px-2 py-1 rounded-full border border-white/10 text-muted-foreground hover:text-foreground hover:border-white/20 transition-colors"
        >
          <FileDown className="w-3 h-3" /> .eml
        </button>
      </div>
      <div className="p-4 space-y-2">
        <div className="flex gap-2 items-center text-xs">
          <span className="text-muted-foreground/50 w-16 flex-shrink-0">To</span>
          <input
            value={preview.to || ""}
            placeholder="Recipient email"
            onChange={(e) => onPreviewChange({ to: e.target.value })}
            readOnly={!editing}
            className={`flex-1 bg-transparent border-b outline-none py-1 ${editing ? "border-white/10 focus:border-primary" : "border-transparent"}`}
          />
        </div>
        <div className="flex gap-2 items-center text-xs">
          <span className="text-muted-foreground/50 w-16 flex-shrink-0">Subject</span>
          <input
            value={preview.subject || ""}
            onChange={(e) => onPreviewChange({ subject: e.target.value })}
            readOnly={!editing}
            className={`flex-1 bg-transparent border-b outline-none py-1 font-medium ${editing ? "border-white/10 focus:border-primary" : "border-transparent"}`}
          />
        </div>
        <div className="pt-2 mt-1 border-t border-white/5">
          <textarea
            value={preview.body || ""}
            onChange={(e) => onPreviewChange({ body: e.target.value })}
            readOnly={!editing}
            rows={6}
            className="w-full bg-transparent outline-none text-xs font-sans text-muted-foreground leading-relaxed resize-y border-0"
          />
        </div>
        {artifacts.length > 0 && (
          <div className="space-y-1.5 border-t border-white/5 pt-3">
            {artifacts.map((artifact, index) => (
              <div key={`${artifact.name}-${index}`} className="flex items-center gap-2 rounded-lg border border-white/6 bg-white/[0.02] px-3 py-2">
                <Paperclip className="h-3.5 w-3.5 flex-shrink-0 text-primary" />
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">{artifact.name}</p>
                  <p className="text-[10px] text-muted-foreground/60">
                    {artifact.source || "Prepared by AURA"}
                    {artifact.size != null ? ` · ${formatBytes(artifact.size)}` : ""}
                  </p>
                </div>
                <span className={`ml-auto text-[10px] ${artifact.verified ? "text-emerald-300/80" : "text-amber-200/80"}`}>
                  {artifact.verified ? "Verified PDF ready" : "PDF will be attached"}
                </span>
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
        <span className="text-xs font-medium">Action details</span>
        <span className="ml-auto text-[10px] text-muted-foreground/50">{fields.length} {fields.length === 1 ? "field" : "fields"}</span>
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
  const phaseLimit = contract.fields?.find((field) => field.key === "phases")?.max_items || 4;
  const [selectedSlide, setSelectedSlide] = useState(0);
  useEffect(() => {
    setSelectedSlide((current) => Math.max(0, Math.min(current, Math.max(0, phases.length - 1))));
  }, [phases.length]);
  const updatePhase = (index, patch) => {
    const next = phases.map((phase, phaseIndex) => phaseIndex === index ? { ...phase, ...patch } : phase);
    onArgumentsChange({ ...args, phases: next });
  };
  const active = phases[selectedSlide] || { period: "", title: "Add a slide", items: [] };

  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-xl border border-white/8 bg-[#11131a] shadow-inner">
        <div className="flex flex-wrap items-center gap-2 border-b border-white/8 bg-[#171923] px-4 py-2.5">
          <Presentation className="h-3.5 w-3.5 text-cyan-300" />
          <span className="text-xs font-medium">Canva presentation preview</span>
          <span className="ml-auto rounded-full border border-white/8 px-2 py-1 text-[10px] text-muted-foreground">
            {phases.length} {phases.length === 1 ? "slide" : "slides"} · editable here
          </span>
        </div>
        <div className="border-b border-white/8 bg-[#1d202b] px-3 py-2">
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              aria-label="Presentation title"
              value={args.title || ""}
              onChange={(event) => onArgumentsChange({ ...args, title: event.target.value })}
              readOnly={!editing}
              placeholder="Presentation title"
              className="rounded-md border border-white/8 bg-black/15 px-3 py-1.5 text-xs font-medium text-white outline-none focus:border-violet-300"
            />
            <input
              aria-label="Presentation subtitle"
              value={args.subtitle || ""}
              onChange={(event) => onArgumentsChange({ ...args, subtitle: event.target.value })}
              readOnly={!editing}
              placeholder="Subtitle"
              className="rounded-md border border-white/8 bg-black/15 px-3 py-1.5 text-xs text-slate-300 outline-none focus:border-violet-300"
            />
          </div>
        </div>
        <div className="grid min-h-[25rem] grid-cols-[6.5rem_minmax(0,1fr)] bg-[#20222c]">
          <div className="space-y-2 overflow-y-auto border-r border-white/8 bg-[#171923] p-2">
            {phases.map((phase, index) => (
              <button
                type="button"
                key={index}
                onClick={() => setSelectedSlide(index)}
                className={`w-full rounded-lg border p-1.5 text-left transition-colors ${selectedSlide === index ? "border-violet-400/70 bg-violet-400/10" : "border-white/8 bg-black/10 hover:border-white/20"}`}
              >
                <span className="block text-[9px] text-muted-foreground">{index + 1}</span>
                <span className="mt-1 block line-clamp-2 text-[9px] font-medium leading-tight text-white">{phase.title || "Untitled slide"}</span>
              </button>
            ))}
            {editing && phases.length < phaseLimit && (
              <button
                type="button"
                onClick={() => {
                  onArgumentsChange({ ...args, phases: [...phases, { period: "", title: "", items: [""] }] });
                  setSelectedSlide(phases.length);
                }}
                className="flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-white/15 px-2 py-3 text-[9px] text-muted-foreground hover:border-violet-300/50 hover:text-violet-200"
              >
                <Plus className="h-3 w-3" /> Add slide
              </button>
            )}
          </div>
          <div className="flex items-center justify-center p-4 sm:p-6">
            <div className="relative aspect-video w-full max-w-2xl overflow-hidden rounded-md bg-[#0b1625] p-6 shadow-2xl sm:p-9">
              <p className="mb-5 text-[9px] font-semibold text-slate-400 sm:text-[11px]">{args.title || "Untitled presentation"}</p>
              {editing ? (
                <>
                  <input aria-label={`Slide ${selectedSlide + 1} period`} value={active.period || ""} onChange={(event) => updatePhase(selectedSlide, { period: event.target.value })} placeholder="Date or section" className="w-full border-b border-white/10 bg-transparent text-[9px] font-semibold uppercase tracking-wide text-emerald-300 outline-none focus:border-emerald-300" />
                  <input aria-label={`Slide ${selectedSlide + 1} title`} value={active.title || ""} onChange={(event) => updatePhase(selectedSlide, { title: event.target.value })} placeholder="Slide title" className="mt-2 w-full border-b border-white/10 bg-transparent text-lg font-semibold text-white outline-none focus:border-cyan-300 sm:text-2xl" />
                  <textarea aria-label={`Slide ${selectedSlide + 1} items`} value={(active.items || []).join("\n")} onChange={(event) => updatePhase(selectedSlide, { items: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })} rows={5} placeholder="One point per line" className="mt-4 w-full resize-none border-b border-white/10 bg-transparent text-xs leading-relaxed text-slate-300 outline-none focus:border-cyan-300" />
                </>
              ) : (
                <>
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300">{active.period}</p>
                  <p className="mt-2 text-lg font-semibold text-white sm:text-2xl">{active.title}</p>
                  <div className="mt-4 space-y-2">
                    {(active.items || []).slice(0, 7).map((item, itemIndex) => <p key={itemIndex} className="text-xs text-slate-300">• {item}</p>)}
                  </div>
                </>
              )}
              <div className="absolute inset-x-6 bottom-5 flex items-end gap-3 text-[9px] text-slate-500 sm:inset-x-9">
                <span className="min-w-0 flex-1 truncate">{args.subtitle || ""}</span>
                <span className="font-semibold text-cyan-300">{selectedSlide + 1} / {Math.max(1, phases.length)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {editing && phases.length > 1 && (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => onArgumentsChange({ ...args, phases: phases.filter((_, index) => index !== selectedSlide) })}
            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-rose-300"
          >
            <Trash2 className="h-3 w-3" /> Remove this slide
          </button>
        </div>
      )}
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
  const liveProvider = richPresentation ? "canva" : richEmail ? "gmail" : null;
  const [editing, setEditing] = useState(() => richEmail || richPresentation || richDocument);
  const updateArguments = (nextArguments) => {
    const patch = {
      arguments: nextArguments,
      resolvedArguments: nextArguments,
    };
    if (richEmail) {
      patch.preview = {
        ...p,
        to: nextArguments.to || "",
        subject: nextArguments.subject || "",
        body: nextArguments.body || "",
      };
    } else if (richTicket) {
      patch.preview = {
        ...p,
        project: nextArguments.project_key || nextArguments.projectKey || nextArguments.project || "",
        summary: nextArguments.summary || "",
        description: nextArguments.description || "",
        assignee: nextArguments.assignee_id || nextArguments.assignee || "",
      };
    } else if (richDocument) {
      patch.preview = {
        ...p,
        docTitle: nextArguments.title || nextArguments.name || nextArguments.summary || "",
        docBody: nextArguments.body ?? nextArguments.content ?? nextArguments.description ?? "",
      };
    }
    onUpdate(index, patch);
  };
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
    <div className="rounded-2xl border border-amber-400/20 bg-amber-400/[0.03] p-4">
      <div className="flex items-start gap-3 mb-3">
        <div className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold bg-amber-400/10 border border-amber-400/20 text-amber-300">
          {number}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap mb-1">
            <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/50">{step.tool}</span>
            <span className="flex items-center gap-1 text-[10px] text-amber-400">
              <ShieldAlert className="w-2.5 h-2.5" /> needs your review
            </span>
            <button
              onClick={() => setEditing((e) => !e)}
              className={`ml-auto flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] transition-colors ${editing ? "border-primary/30 bg-primary/10 text-primary" : "border-white/10 text-muted-foreground hover:text-primary"}`}
            >
              <Pencil className="w-2.5 h-2.5" /> {editing ? "Editing" : "Edit in AURA"}
            </button>
          </div>
          <p className="py-0.5 text-sm font-medium">{step.action || contract.title}</p>
          {step.riskNote && <p className="text-[11px] text-amber-300/70 mt-1">{step.riskNote}</p>}
        </div>
      </div>
      <div className="pl-10 space-y-3">
        {liveToolReviewEnabled && liveProvider && (
          <LiveToolReview
            provider={liveProvider}
            label={liveProvider === "canva" ? "Canva" : "Gmail"}
          />
        )}
        {step.reviewContract ? (
          <>
            {richEmail && <EditableEmail preview={p} onPreviewChange={updatePreview} editing={editing} artifacts={contract.artifacts || []} />}
            {richTicket && <EditableJiraTask preview={p} onPreviewChange={updatePreview} editing={editing} />}
            {richDocument && <EditableDocument preview={p} onPreviewChange={updatePreview} editing={editing} />}
            {richPresentation && (
              <EditablePresentation
                args={args}
                contract={contract}
                editing={editing}
                onArgumentsChange={updateArguments}
              />
            )}
            {!richEmail && !richTicket && !richPresentation && !richDocument && (
              <SchemaArgumentsEditor
                contract={contract}
                args={args}
                editing={editing}
                onArgumentsChange={updateArguments}
                onFieldValidity={fieldValidity}
                excludeKeys={[]}
              />
            )}
            {(richEmail || richTicket || richPresentation || richDocument) && (
              <PromptApprovalEditor
                step={step}
                args={args}
                onArgumentsChange={updateArguments}
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
    .filter(({ step }) => step.riskLevel !== "modify" && !step.approvalPending);
  const destinationTools = [...new Set(reviewSteps.map(({ step }) => step.tool))];
  const contractErrors = reviewSteps.flatMap(({ step, index }) => (
    step.reviewContract
      ? validateReviewArguments(step.reviewContract, step.resolvedArguments || step.arguments || {})
        .map((error) => ({ ...error, stepIndex: index }))
      : []
  ));
  const approvalBlocked = invalidFields.size > 0 || contractErrors.length > 0;
  const reviewSummary = `${reviewSteps.length} resolved ${destinationTools.join(" / ")} ${reviewSteps.length === 1 ? "change is" : "changes are"} ready for your review.`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.4 }}
      className="w-full max-w-2xl mx-auto"
    >
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2 rounded-xl bg-accent/10 border border-accent/20">
          <Eye className="w-5 h-5 text-accent" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">Review before AURA continues</h2>
          <p className="text-xs text-muted-foreground">Check the resolved content AURA is about to create or send. You can edit available fields before approving.</p>
        </div>
      </div>

      <div className="flex items-center gap-2 mt-5 text-xs text-muted-foreground">
        <Check className="w-3.5 h-3.5 text-emerald-400" />
        <span>{reviewSummary}</span>
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

      <div className="flex items-center justify-between mt-5 mb-2">
        <span className="flex items-center gap-1.5 text-sm font-medium text-amber-200">
          <ShieldAlert className="w-4 h-4 text-amber-400" /> Your approval is needed
        </span>
        <span className="text-[11px] text-muted-foreground">{reviewSteps.length} {reviewSteps.length === 1 ? "change" : "changes"}</span>
      </div>

      {/* Editable steps */}
      <div className="space-y-3 mb-5 mt-4">
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
      <div className="flex items-center justify-between pt-4 border-t border-white/6">
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
            className="bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white border-0 gap-1.5"
          >
            <Play className="w-3.5 h-3.5" />
            {approvalBlocked ? "Waiting for resolved values" : "Approve & continue"}
          </Button>
        </motion.div>
      </div>
    </motion.div>
  );
}
