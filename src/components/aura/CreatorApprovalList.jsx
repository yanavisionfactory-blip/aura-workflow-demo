import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Check, Loader2, Mail, ExternalLink, CheckCircle2, Pencil, ChevronDown, Save, X } from "lucide-react";
import { base44 } from "@/api/base44Client";

// Renders the creators AURA discovered. For each, you can preview and EDIT
// the outreach draft (subject + body) before approving. Approving marks the
// Creator "approved" — the scheduled "Send Approved Outreach" job then sends
// the (edited) draft. Nothing is sent until you approve here.

export default function CreatorApprovalList({ items: initialItems }) {
  const [items, setItems] = useState(initialItems || []);
  const [busy, setBusy] = useState(null);
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState({});

  const startEdit = (it) => {
    setEditing(it.id);
    setDraft({ subject: it.subject || "", body: it.body || "" });
  };

  const cancelEdit = () => {
    setEditing(null);
    setDraft({});
  };

  const saveDraft = async (id) => {
    setBusy(id);
    try {
      await base44.entities.Creator.update(id, { outreach_subject: draft.subject, outreach_draft: draft.body });
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, subject: draft.subject, body: draft.body } : it)));
      setEditing(null);
      setDraft({});
    } catch {}
    setBusy(null);
  };

  const approve = async (id) => {
    setBusy(id);
    try {
      await base44.entities.Creator.update(id, { status: "approved" });
      setItems((prev) => prev.map((it) => (it.id === id ? { ...it, status: "approved" } : it)));
    } catch {}
    setBusy(null);
  };

  if (!items.length) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.25 }}
      className="mb-6 p-4 rounded-xl border border-amber-400/20 bg-amber-400/[0.03]"
    >
      <div className="flex items-center gap-2 mb-1">
        <Mail className="w-4 h-4 text-amber-400" />
        <h3 className="text-sm font-medium">Ready for your approval</h3>
      </div>
      <p className="text-xs text-muted-foreground mb-3">
        Review and edit each draft, then approve. AURA sends the email only after you approve — nothing goes out until then.
      </p>
      <div className="space-y-2">
        {items.map((it) => {
          const approved = it.status === "approved";
          const isEditing = editing === it.id;
          return (
            <div key={it.id} className="rounded-lg bg-card/50 border border-white/6 overflow-hidden">
              <div className="flex items-center gap-3 p-2.5">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{it.label}</p>
                  <p className="text-[11px] text-muted-foreground truncate">{it.detail}</p>
                </div>
                {approved ? (
                  <span className="flex items-center gap-1 text-[11px] text-emerald-400 px-2 py-1 rounded-md bg-emerald-400/10 border border-emerald-400/20 shrink-0">
                    <CheckCircle2 className="w-3.5 h-3.5" /> Approved
                  </span>
                ) : (
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      onClick={() => (isEditing ? cancelEdit() : startEdit(it))}
                      className="flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-md bg-white/5 text-foreground border border-white/10 hover:bg-white/10 transition-colors"
                    >
                      {isEditing ? <X className="w-3 h-3" /> : <Pencil className="w-3 h-3" />}
                      {isEditing ? "Cancel" : "Edit"}
                    </button>
                    <button
                      onClick={() => approve(it.id)}
                      disabled={busy === it.id}
                      className="flex items-center gap-1 text-[11px] px-2.5 py-1.5 rounded-md bg-amber-400/15 text-amber-400 border border-amber-400/30 hover:bg-amber-400/25 transition-colors disabled:opacity-50"
                    >
                      {busy === it.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                      Approve
                    </button>
                  </div>
                )}
              </div>

              {/* Draft preview / editor */}
              <AnimatePresence initial={false}>
                {isEditing ? (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="border-t border-white/6 px-3 py-3 space-y-2"
                  >
                    <input
                      value={draft.subject || ""}
                      onChange={(e) => setDraft((d) => ({ ...d, subject: e.target.value }))}
                      placeholder="Subject"
                      className="w-full text-xs px-2.5 py-2 rounded-md bg-background/60 border border-white/10 focus:border-primary/40 focus:outline-none"
                    />
                    <textarea
                      value={draft.body || ""}
                      onChange={(e) => setDraft((d) => ({ ...d, body: e.target.value }))}
                      placeholder="Email body"
                      rows={6}
                      className="w-full text-xs px-2.5 py-2 rounded-md bg-background/60 border border-white/10 focus:border-primary/40 focus:outline-none resize-y"
                    />
                    <div className="flex justify-end">
                      <button
                        onClick={() => saveDraft(it.id)}
                        disabled={busy === it.id}
                        className="flex items-center gap-1 text-[11px] px-3 py-1.5 rounded-md bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 transition-colors disabled:opacity-50"
                      >
                        {busy === it.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                        Save draft
                      </button>
                    </div>
                  </motion.div>
                ) : (
                  <button
                    onClick={() => startEdit(it)}
                    className="w-full text-left border-t border-white/6 px-3 py-2 hover:bg-white/[0.02] transition-colors"
                  >
                    <p className="text-[11px] text-muted-foreground/60 mb-0.5">Subject</p>
                    <p className="text-xs font-medium truncate">{it.subject || "(no subject)"}</p>
                    <p className="text-[11px] text-muted-foreground/60 mt-1 mb-0.5">Body</p>
                    <p className="text-[11px] text-muted-foreground line-clamp-2 whitespace-pre-wrap">{it.body || "(no body)"}</p>
                    <span className="inline-flex items-center gap-1 text-[10px] text-primary/70 mt-1.5">
                      <Pencil className="w-2.5 h-2.5" /> Click to edit
                    </span>
                  </button>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
      <a
        href="https://mgr-approver.vercel.app/"
        target="_blank"
        rel="noreferrer"
        className="mt-3 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <ExternalLink className="w-3 h-3" /> Check each creator in the Grail approver form before approving
      </a>
    </motion.div>
  );
}