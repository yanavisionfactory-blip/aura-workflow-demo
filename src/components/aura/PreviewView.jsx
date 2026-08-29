import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Eye, Mail, Database, ShieldAlert, ArrowLeft, Play, List, FileDown, FileText, Pencil, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { downloadEmailEml, safeName } from "@/lib/auraDownload";

function EditableEmail({ preview, onPreviewChange, editing }) {
  return (
    <div className="rounded-xl border border-white/8 bg-card/40 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/6 bg-card/30">
        <Mail className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-medium">Email</span>
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

function EditableDocument({ preview, onPreviewChange, editing }) {
  return (
    <div className="rounded-xl border border-white/8 bg-card/40 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/6 bg-card/30">
        <FileText className="w-3.5 h-3.5 text-accent" />
        <span className="text-xs font-medium">Document</span>
        <button
          onClick={() => downloadEmailEml(`aura-doc-${safeName(preview.docTitle || "draft")}.eml`, { subject: preview.docTitle || "", body: preview.docBody || "" })}
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
      {step.detail && (
        <div className={step.output ? "pt-2 border-t border-white/5" : ""}>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground/50">Details</span>
          <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{step.detail}</p>
        </div>
      )}
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

function EditableStepCard({ step, number, index, onUpdate }) {
  const p = step.preview || {};
  const isModify = step.riskLevel === "modify";
  const [editing, setEditing] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const updateAction = (action) => onUpdate(index, { action });
  const updatePreview = (patch) => onUpdate(index, { preview: { ...(step.preview || {}), ...patch } });

  // Read-only step (data pulled, nothing sent/changed): collapsed + not editable.
  // Tap "show" to reveal the table/list — purely informational, never editable.
  if (!isModify) {
    return (
      <div className="rounded-2xl border border-white/8 bg-card/30">
        <div className="flex items-start gap-3 p-4">
          <div className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold bg-accent/10 border border-accent/20 text-accent">
            {number}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/50">{step.tool}</span>
              <span className="text-[10px] text-muted-foreground/40">read-only</span>
              <button
                onClick={() => setShowPreview((s) => !s)}
                className="flex items-center gap-0.5 text-[10px] text-muted-foreground/60 hover:text-accent ml-auto transition-colors"
              >
                {showPreview ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {showPreview ? "hide" : "show"}
              </button>
            </div>
            <p className="text-sm font-medium">{step.action}</p>
          </div>
        </div>
        <AnimatePresence initial={false}>
          {showPreview && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="pl-10 pr-4 pb-4">
                {p.type === "table" ? <ApprovalTable preview={p} />
                  : p.type === "list" ? <ApprovalList preview={p} />
                  : <FallbackPreview step={step} />}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }

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
              className="flex items-center gap-0.5 text-[10px] text-muted-foreground/60 hover:text-primary ml-auto transition-colors"
            >
              <Pencil className="w-2.5 h-2.5" /> {editing ? "done" : "edit"}
            </button>
          </div>
          <input
            value={step.action || ""}
            onChange={(e) => updateAction(e.target.value)}
            readOnly={!editing}
            className={`w-full bg-transparent text-sm font-medium border-b outline-none py-0.5 ${editing ? "border-white/8 focus:border-primary" : "border-transparent"}`}
          />
          {step.riskNote && <p className="text-[11px] text-amber-300/70 mt-1">{step.riskNote}</p>}
        </div>
      </div>
      <div className="pl-10">
        {p.type === "email" ? <EditableEmail preview={p} onPreviewChange={updatePreview} editing={editing} />
          : p.type === "document" ? <EditableDocument preview={p} onPreviewChange={updatePreview} editing={editing} />
          : p.type === "table" ? <ApprovalTable preview={p} />
          : p.type === "list" ? <ApprovalList preview={p} />
          : <FallbackPreview step={step} />}
      </div>
    </div>
  );
}

export default function PreviewView({ preview, steps, onApprove, onBack }) {
  const initial = steps && steps.length ? steps : preview?.steps || [];
  const [editSteps, setEditSteps] = useState(
    initial.map((s) => ({ ...s, preview: s.preview ? { ...s.preview } : s.preview }))
  );
  if (!editSteps.length) return null;

  const update = (i, patch) => setEditSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));

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
          <h2 className="text-lg font-semibold">Review &amp; edit before running</h2>
          <p className="text-xs text-muted-foreground">Edit any step's content — your changes drive the execution.</p>
        </div>
      </div>

      {/* Editable steps */}
      <div className="space-y-3 mb-5 mt-4">
        {editSteps.map((step, i) => (
          <EditableStepCard key={i} step={step} number={i + 1} index={i} onUpdate={update} />
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-4 border-t border-white/6">
        <Button variant="ghost" size="sm" onClick={onBack} className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
          Back to plan
        </Button>
        <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
          <Button
            size="sm"
            onClick={() => onApprove(editSteps)}
            className="bg-gradient-to-r from-emerald-500 to-emerald-600 hover:from-emerald-600 hover:to-emerald-700 text-white border-0 gap-1.5"
          >
            <Play className="w-3.5 h-3.5" />
            Approve &amp; run
          </Button>
        </motion.div>
      </div>
    </motion.div>
  );
}