import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, ArrowRight, Sparkles, CheckCircle2, Loader2 } from "lucide-react";
import { base44 } from "@/api/base44Client";

export default function AccessRequestModal({ open, onClose, workflowPrompt }) {
  const [form, setForm] = useState({
    full_name: "",
    work_email: "",
    company: "",
  });
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    await base44.entities.AccessRequest.create({ ...form, workflow_prompt: workflowPrompt || "" });
    setLoading(false);
    setSubmitted(true);
  };

  const handleClose = () => {
    onClose();
    setTimeout(() => setSubmitted(false), 400);
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={handleClose}
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", stiffness: 260, damping: 25 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
          >
            <div className="w-full max-w-md bg-card border border-white/10 rounded-2xl shadow-2xl pointer-events-auto overflow-hidden">
              {submitted ? (
                <SuccessState onClose={handleClose} />
              ) : (
                <FormState
                  form={form}
                  set={set}
                  loading={loading}
                  onSubmit={handleSubmit}
                  onClose={handleClose}
                />
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function FormState({ form, set, loading, onSubmit, onClose }) {
  return (
    <div>
      {/* Header */}
      <div className="px-6 pt-6 pb-4 border-b border-white/6 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2 mb-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/15 border border-primary/25 text-[11px] font-medium text-primary">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            Currently in private beta
          </div>
        </div>
        <h2 className="text-xl font-bold mb-1">Request access to AURA</h2>
        <p className="text-sm text-muted-foreground">
          Drop your details — we'll get back to you shortly.
        </p>
      </div>

      <form onSubmit={onSubmit} className="px-6 py-5 space-y-5">
        <div className="space-y-3">
          <Field label="Full name" placeholder="Jane Smith" value={form.full_name} onChange={v => set("full_name", v)} required />
          <Field label="Work email" placeholder="jane@company.com" type="email" value={form.work_email} onChange={v => set("work_email", v)} required />
          <Field label="Company / team name" placeholder="Acme Corp" value={form.company} onChange={v => set("company", v)} />
        </div>

        <motion.button
          type="submit"
          disabled={loading || !form.full_name || !form.work_email}
          whileHover={{ scale: 1.01 }}
          whileTap={{ scale: 0.99 }}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-gradient-to-r from-primary to-primary/80 text-white font-semibold text-sm disabled:opacity-50 transition-opacity shadow-lg shadow-primary/20"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Request access <ArrowRight className="w-4 h-4" /></>}
        </motion.button>

        <p className="text-center text-[11px] text-muted-foreground/50 leading-relaxed">
          We'll review your request and get back to you within 24–48 hours.
        </p>
      </form>
    </div>
  );
}

function Field({ label, placeholder, value, onChange, type = "text", required }) {
  return (
    <div>
      <label className="block text-sm mb-1.5">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="w-full bg-secondary/60 border border-white/8 rounded-xl px-3 py-2.5 text-sm outline-none focus:border-primary/40 transition-colors placeholder:text-muted-foreground/40"
      />
    </div>
  );
}

function SuccessState({ onClose }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex flex-col items-center text-center px-8 py-12"
    >
      <div className="inline-flex p-4 rounded-2xl bg-emerald-400/10 border border-emerald-400/20 mb-5">
        <CheckCircle2 className="w-8 h-8 text-emerald-400" />
      </div>
      <h3 className="text-xl font-bold mb-2">You're on the list</h3>
      <p className="text-sm text-muted-foreground mb-6">
        We'll review your request and reach out within 24–48 hours. We prioritize teams actively building workflows.
      </p>
      <button
        onClick={onClose}
        className="px-6 py-2.5 rounded-xl border border-white/10 text-sm hover:bg-white/5 transition-colors"
      >
        Back to AURA
      </button>
    </motion.div>
  );
}