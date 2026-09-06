import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Pencil, Search, Plus } from "lucide-react";
import { CATALOG } from "@/lib/toolCatalog";

// Inline editor for the "Uses" line on a plan step. The user can pick a known
// tool from the catalog or type their own — an internal base, a document, or
// any tool AURA doesn't know yet. Connection state is deliberately not shown
// here: the plan has one dedicated notification listing only missing apps.
export default function ToolPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef(null);

  const entry = CATALOG.find((t) => t.name === value);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const q = query.trim().toLowerCase();
  const filtered = CATALOG.filter((t) => t.name.toLowerCase().includes(q));
  const exactMatch = CATALOG.some((t) => t.name.toLowerCase() === q);
  const canAddCustom = q.length > 0 && !exactMatch;

  const select = (name) => {
    onChange(name);
    setOpen(false);
    setQuery("");
  };

  return (
    <div className="relative" ref={ref}>
      <div className="inline-flex items-center gap-1.5 text-[11px] pl-2.5 pr-1.5 py-1 rounded-lg bg-primary/5 border border-primary/10">
        <span className="text-primary/50 font-medium">Uses:</span>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1 text-foreground/80 hover:text-foreground transition-colors"
        >
          <span>{entry?.icon ? `${entry.icon} ` : ""}{value}</span>
          <Pencil className="w-2.5 h-2.5 text-muted-foreground/60" />
        </button>
      </div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute left-0 top-full mt-1 z-30 w-64 rounded-xl border border-white/10 bg-popover shadow-2xl overflow-hidden"
          >
            <div className="p-2 border-b border-white/6">
              <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-card/70 border border-white/8">
                <Search className="w-3.5 h-3.5 text-muted-foreground/60 flex-shrink-0" />
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search or type a tool…"
                  className="flex-1 min-w-0 bg-transparent outline-none text-sm placeholder:text-muted-foreground/40"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && canAddCustom) select(query.trim());
                    if (e.key === "Escape") setOpen(false);
                  }}
                />
              </div>
            </div>
            <div className="max-h-56 overflow-y-auto py-1">
              {filtered.map((t) => (
                <button
                  key={t.name}
                  type="button"
                  onClick={() => select(t.name)}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-white/5 transition-colors ${value === t.name ? "bg-primary/10" : ""}`}
                >
                  <span className="text-base flex-shrink-0">{t.icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{t.name}</p>
                    <p className="text-[10px] text-muted-foreground truncate">{t.desc}</p>
                  </div>
                </button>
              ))}
              {filtered.length === 0 && !canAddCustom && (
                <p className="text-center text-xs text-muted-foreground py-4">No tools found</p>
              )}
              {canAddCustom && (
                <button
                  type="button"
                  onClick={() => select(query.trim())}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-primary/10 border-t border-white/6 transition-colors"
                >
                  <span className="p-1 rounded-lg bg-primary/10 border border-primary/20 flex-shrink-0">
                    <Plus className="w-3 h-3 text-primary" />
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">Add “{query.trim()}”</p>
                    <p className="text-[10px] text-muted-foreground">Custom tool, base, or document</p>
                  </div>
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
