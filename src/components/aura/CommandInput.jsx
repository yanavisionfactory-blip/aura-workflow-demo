import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, Sparkles, X, Plus, FileBarChart, Mail, ListChecks, RefreshCw, Paperclip } from "lucide-react";
import ValueProp from "./ValueProp";
import ResourceComposer from "./ResourceComposer";
import AuraInterfaceConnect from "./AuraInterfaceConnect";
import { recordInterfaceConnection } from "@/lib/connectService";
import { base44 } from "@/api/base44Client";

const EXAMPLE_ICONS = [FileBarChart, Mail, ListChecks, RefreshCw];

const toolHints = [
  { keywords: ["lead", "crm", "contact", "deal", "pipeline"], label: "HubSpot" },
  { keywords: ["slack", "notify", "message", "team", "channel", "ping"], label: "Slack" },
  { keywords: ["email", "send", "gmail", "inbox", "follow-up", "follow up"], label: "Gmail" },
  { keywords: ["calendar", "schedule", "meeting", "book", "invite"], label: "Google Calendar" },
  { keywords: ["salesforce", "opportunity", "account", "sf"], label: "Salesforce" },
  { keywords: ["notion", "doc", "document", "page", "note", "wiki"], label: "Notion" },
  { keywords: ["sheet", "spreadsheet", "report", "csv", "data"], label: "Google Sheets" },
  { keywords: ["meta", "ads", "campaign", "facebook"], label: "Meta Ads" },
  { keywords: ["ticket", "support", "issue", "jira", "bug", "task"], label: "Jira" },
];

function getHints(text) {
  if (!text) return [];
  const lower = text.toLowerCase();
  return toolHints.filter((h) => h.keywords.some((k) => lower.includes(k))).map((h) => h.label).slice(0, 3);
}

export default function CommandInput({ onSubmit, disabled, examples, onPickExample }) {
  const [value, setValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const [manualTools, setManualTools] = useState([]);
  const [removedTools, setRemovedTools] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [showComposer, setShowComposer] = useState(false);
  const [interfaceTool, setInterfaceTool] = useState(null);
  const [interfaceError, setInterfaceError] = useState("");
  const [examplesCollapsed, setExamplesCollapsed] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    base44.entities.WorkflowRun.list("-created_date", 50)
      .then((runs) => {
        const done = (runs || []).filter((r) => r.status === "completed");
        if (done.length >= 3) setExamplesCollapsed(true);
      })
      .catch(() => {});
  }, []);

  const autoHints = getHints(value).filter((h) => !removedTools.includes(h));
  const hints = [...new Set([...autoHints, ...manualTools])];

  const handleSubmit = () => {
    const text = value.trim();
    if (text && !disabled) {
      onSubmit(text, hints, { tools: hints, documents });
      setValue("");
    }
  };

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: "easeOut" }} className="w-full max-w-3xl mx-auto">
      <ValueProp />

      {/* Input box */}
      <div
        className={`relative rounded-2xl border transition-all duration-300 ${isFocused ? "border-primary/50 glow-primary" : "border-white/8"} bg-card/80 backdrop-blur-sm`}
      >
        <div className="flex items-start p-4 gap-3">
          <div className="mt-1 p-1.5 rounded-lg bg-primary/10">
            <Sparkles className="w-4 h-4 text-primary" />
          </div>
          <textarea
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            placeholder="Tell AURA what you want to get done… e.g. Create a weekly campaign report and send it to my team"
            disabled={disabled}
            rows={2}
            className="flex-1 bg-transparent border-none outline-none resize-none text-sm leading-relaxed placeholder:text-muted-foreground/60 disabled:opacity-50"
          />
        </div>

        {/* Tool hints */}
        <AnimatePresence>
          {value.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="px-4 pb-2 flex items-center gap-1.5 flex-wrap"
            >
              <span className="text-[10px] text-muted-foreground/35">AURA will use</span>
              {hints.map((h) => (
                <motion.button
                  key={h}
                  initial={{ opacity: 0, scale: 0.85 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.85 }}
                  onClick={() => {
                    setRemovedTools((prev) => [...prev, h]);
                    setManualTools((prev) => prev.filter((t) => t !== h));
                  }}
                  className="group flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-primary/8 text-primary/60 border border-primary/15 hover:bg-red-500/10 hover:border-red-400/20 hover:text-red-400/70 transition-all"
                >
                  {h}
                  <X className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                </motion.button>
              ))}
              {documents.map((d) => (
                <motion.button
                  key={d.file_url}
                  initial={{ opacity: 0, scale: 0.85 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.85 }}
                  onClick={() => setDocuments((prev) => prev.filter((x) => x.file_url !== d.file_url))}
                  className="group flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-accent/8 text-accent/70 border border-accent/15 hover:bg-red-500/10 hover:border-red-400/20 hover:text-red-400/70 transition-all max-w-[180px]"
                >
                  <Paperclip className="w-2.5 h-2.5 shrink-0" />
                  <span className="truncate">{d.name}</span>
                  <X className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                </motion.button>
              ))}
              <div className="relative">
                <button
                  onClick={() => setShowComposer((p) => !p)}
                  className="flex items-center gap-1 text-[10px] px-2.5 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary/60 hover:bg-primary/20 hover:border-primary/40 hover:text-primary/90 transition-all font-medium"
                >
                  <Plus className="w-2.5 h-2.5" /> add
                </button>
                <ResourceComposer
                  open={showComposer}
                  onClose={() => setShowComposer(false)}
                  pinnedTools={hints}
                  pinnedDocs={documents}
                  onAddTool={(name) => {
                    setManualTools((prev) => [...new Set([...prev, name])]);
                    setRemovedTools((prev) => prev.filter((r) => r !== name));
                  }}
                  onAddDocument={(doc) => {
                    setDocuments((prev) => (prev.some((x) => x.file_url === doc.file_url) ? prev : [...prev, doc]));
                    setShowComposer(false);
                  }}
                  onInterfaceTool={(name) => setInterfaceTool(name)}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <AuraInterfaceConnect
          open={!!interfaceTool}
          toolName={interfaceTool}
          onClose={() => setInterfaceTool(null)}
          onConnect={async (name, meta) => {
            try {
              setInterfaceError("");
              await recordInterfaceConnection(name, meta);
              setInterfaceTool(null);
            } catch (e) {
              setInterfaceError(e.message || "This web application could not be connected.");
            }
          }}
        />
        {interfaceError && <p className="mx-4 mb-2 text-xs text-red-400">{interfaceError}</p>}

        <div className="flex items-center justify-between px-4 pb-3">
          <span className="text-[11px] text-muted-foreground/60">Press Enter to run · Shift+Enter for a new line</span>
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={handleSubmit}
            disabled={disabled || !value.trim()}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-primary to-primary/80 text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-40"
          >
            Create plan
            <ArrowRight className="w-4 h-4" />
          </motion.button>
        </div>
      </div>

      {/* Example cards — stay visible, just less prominent once you've run a few workflows */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4 }}
        className={`mt-6 ${examplesCollapsed ? "opacity-60 hover:opacity-100 transition-opacity" : ""}`}
      >
        <p className="text-[11px] text-muted-foreground/70 text-center mb-3">
          Or start with an example
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 max-w-3xl mx-auto">
          {examples.map((ex, i) => {
            const Icon = EXAMPLE_ICONS[i % EXAMPLE_ICONS.length];
            return (
              <motion.button
                key={ex.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 + i * 0.08 }}
                whileHover={{ y: -2 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => onPickExample(i)}
                disabled={disabled}
                className="group text-left p-3.5 rounded-xl border border-white/8 bg-card/50 hover:bg-card/80 hover:border-primary/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <div className="p-1.5 rounded-lg bg-primary/10 text-primary group-hover:bg-primary/20 transition-colors">
                    <Icon className="w-3.5 h-3.5" />
                  </div>
                  <ArrowRight className="w-3 h-3 text-muted-foreground/30 ml-auto opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                </div>
                <h3 className="text-xs font-semibold leading-tight">{ex.title}</h3>
                <p className="text-[11px] text-muted-foreground/70 mt-1 leading-snug">{ex.subtitle}</p>
              </motion.button>
            );
          })}
        </div>
      </motion.div>
    </motion.div>
  );
}
