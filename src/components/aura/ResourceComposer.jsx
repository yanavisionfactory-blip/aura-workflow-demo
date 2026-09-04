import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, Plus, FileUp, Loader2, Check, Link2, Paperclip, X } from "lucide-react";
import { CATALOG } from "@/lib/toolCatalog";
import { getAllConnections, subscribeConnections } from "@/lib/connectionsStore";
import { connectTool } from "@/lib/connectService";
import { aura } from "@/api/auraClient";
import ConnectToolModal from "./ConnectToolModal";

// The "add" affordance in the command input. Unlike a static tool list, this
// lets the user:
//   1. Connect ANY tool — catalog or a custom one they type — and actually
//      connect it for real (AURA runs its oauth/mcp/interface flow behind the
//      scenes via connectTool).
//   2. Attach a document (or any file) — really uploaded, not metaphorically —
//      so AURA can read it during the workflow.
// Both kinds flow into the plan as resources the workflow can use.

export default function ResourceComposer({ open, onClose, onAddTool, onAddDocument, onInterfaceTool, pinnedTools = [], pinnedDocs = [] }) {
  const [tab, setTab] = useState("tools");
  const [query, setQuery] = useState("");
  const [connecting, setConnecting] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [connections, setConnections] = useState(getAllConnections);
  const [pendingConnect, setPendingConnect] = useState(null);
  const [customToolName, setCustomToolName] = useState("");
  const [customToolDesc, setCustomToolDesc] = useState("");
  const fileRef = useRef(null);

  useEffect(() => subscribeConnections(setConnections), []);

  const q = query.trim().toLowerCase();
  const filtered = CATALOG.filter((t) => t.name.toLowerCase().includes(q));
  const customName = query.trim();
  const canAddCustom = customName.length > 0 && !CATALOG.some((t) => t.name.toLowerCase() === customName.toLowerCase());

  // Selecting a tool pins it to "AURA will use". If the tool isn't connected
  // yet, a popup opens asking the user to connect it as a separate step.
  const select = (name) => {
    if (pinnedTools.includes(name)) return;
    onAddTool(name);
    if (!connections[name]) {
      const tool = CATALOG.find((t) => t.name === name);
      setPendingConnect(tool || { name, interface: false, desc: "" });
    }
  };

  const connectOne = async (name) => {
    setConnecting(name);
    try {
      const res = await connectTool(name);
      if (res.interfaceTool) onInterfaceTool(name);
    } catch {
      // non-fatal — user can retry from the plan
    }
    setConnecting(null);
  };

  const confirmConnect = async (toolObj) => {
    if (!pendingConnect) return;
    await connectOne(toolObj?.name || pendingConnect.name);
    setPendingConnect(null);
  };

  // Custom (non-catalog) tools: pin + open the AURA Interface learn flow, since
  // "connect" for them IS the interface-learning modal.
  const addCustom = async (name) => {
    setConnecting(name);
    try {
      const res = await connectTool(name);
      if (res.interfaceTool) onInterfaceTool(name);
      onAddTool(name);
    } catch {
      onAddTool(name);
    }
    setConnecting(null);
  };

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const out = await aura.integrations.Core.UploadFile({ file });
      onAddDocument({ name: file.name, file_url: out.file_url, size: file.size });
    } catch {
      // non-fatal
    }
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: -4 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: -4 }}
          transition={{ duration: 0.15 }}
          className="absolute bottom-full mb-2 left-0 z-30 w-[320px] bg-card border border-white/10 rounded-xl shadow-2xl overflow-hidden"
        >
          {/* Tabs */}
          <div className="flex items-center gap-1 p-2 border-b border-white/6">
            <button
              onClick={() => setTab("tools")}
              className={`flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg font-medium transition-all ${tab === "tools" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-white/5"}`}
            >
              <Link2 className="w-3 h-3" /> Tools
            </button>
            <button
              onClick={() => setTab("docs")}
              className={`flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg font-medium transition-all ${tab === "docs" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-white/5"}`}
            >
              <Paperclip className="w-3 h-3" /> Documents
            </button>
            <button
              onClick={() => setTab("custom")}
              className={`flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg font-medium transition-all ${tab === "custom" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-white/5"}`}
            >
              <Plus className="w-3 h-3" /> Custom
            </button>
            <button onClick={onClose} className="ml-auto p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-white/5">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {tab === "tools" && (
            <div className="p-2">
              <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-card/70 border border-white/8 mb-2">
                <Search className="w-3.5 h-3.5 text-muted-foreground/60" />
                <input
                  autoFocus
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search a tool, or type one AURA doesn't know…"
                  className="flex-1 bg-transparent outline-none text-[11px] placeholder:text-muted-foreground/40"
                />
              </div>

              <div className="max-h-[220px] overflow-y-auto space-y-0.5">
                {filtered.map((t) => {
                  const isConnected = !!connections[t.name];
                  const isPinned = pinnedTools.includes(t.name);
                  const isConnecting = connecting === t.name;
                  return (
                    <div key={t.name} className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-white/5 transition-colors">
                      <div className="w-7 h-7 rounded-lg bg-secondary border border-white/8 flex items-center justify-center text-sm shrink-0">
                        {t.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-medium truncate">{t.name}</p>
                        <p className="text-[10px] text-muted-foreground/70 truncate">{t.desc}</p>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {isPinned ? (
                          <>
                            <span className="flex items-center gap-1 text-[10px] text-emerald-400 pr-0.5">
                              <Check className="w-3 h-3" /> Selected
                            </span>
                            {!isConnected && (
                              <button
                                onClick={() => setPendingConnect(t)}
                                className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md text-amber-400 hover:bg-amber-400/10 transition-colors"
                              >
                                <Plus className="w-3 h-3" /> Connect
                              </button>
                            )}
                          </>
                        ) : (
                          <button
                            onClick={() => select(t.name)}
                            className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md text-primary hover:bg-primary/10 transition-colors shrink-0"
                          >
                            <Plus className="w-3 h-3" /> Select
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}

                {canAddCustom && (
                  <>
                    {filtered.length > 0 && <div className="h-px bg-white/6 my-1" />}
                    <button
                      onClick={() => addCustom(customName)}
                      disabled={connecting === customName}
                      className="w-full flex items-center gap-2 p-1.5 rounded-lg hover:bg-primary/10 text-left transition-colors disabled:opacity-50"
                    >
                      <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0">
                        <Plus className="w-3.5 h-3.5 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-medium truncate">Connect “{customName}”</p>
                        <p className="text-[10px] text-muted-foreground/70">Custom tool, base, or service — AURA connects it for you</p>
                      </div>
                      {connecting === customName ? <Loader2 className="w-3 h-3 animate-spin text-primary" /> : null}
                    </button>
                  </>
                )}

                {!filtered.length && !canAddCustom && (
                  <p className="text-center text-[10px] text-muted-foreground/60 py-6">Type a tool name to connect it</p>
                )}
              </div>
            </div>
          )}
          {tab === "docs" && (
            <div className="p-3">
              <button
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="w-full flex flex-col items-center justify-center gap-2 py-6 rounded-xl border border-dashed border-white/12 hover:border-primary/30 hover:bg-primary/5 transition-all disabled:opacity-50"
              >
                {uploading ? (
                  <Loader2 className="w-5 h-5 animate-spin text-primary" />
                ) : (
                  <FileUp className="w-5 h-5 text-primary" />
                )}
                <span className="text-[11px] font-medium">{uploading ? "Uploading…" : "Attach a document or file"}</span>
                <span className="text-[10px] text-muted-foreground/60">PDF, CSV, sheet, doc, image — AURA can read it in the workflow</span>
              </button>
              <input ref={fileRef} type="file" className="hidden" onChange={handleFile} />

              {pinnedDocs.length > 0 && (
                <div className="mt-2 space-y-0.5">
                  {pinnedDocs.map((d) => (
                    <div key={d.file_url} className="flex items-center gap-2 p-1.5 rounded-lg bg-white/5">
                      <Paperclip className="w-3 h-3 text-primary shrink-0" />
                      <p className="text-[11px] truncate flex-1">{d.name}</p>
                      <Check className="w-3 h-3 text-emerald-400" />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === "custom" && (
            <div className="p-3 space-y-2">
              <p className="text-[10px] text-muted-foreground/70 leading-relaxed">
                Add a tool you use at work that isn't in AURA's common list. AURA learns its interface to connect it.
              </p>
              <input
                value={customToolName}
                onChange={(e) => setCustomToolName(e.target.value)}
                placeholder="Tool name (e.g. Internal CRM)"
                className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40"
              />
              <input
                value={customToolDesc}
                onChange={(e) => setCustomToolDesc(e.target.value)}
                placeholder="What does it do? (optional)"
                className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40"
              />
              <button
                onClick={() => addCustom(customToolName.trim())}
                disabled={!customToolName.trim() || connecting === customToolName.trim()}
                className="w-full flex items-center justify-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {connecting === customToolName.trim() ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                {connecting === customToolName.trim() ? "Connecting…" : "Connect custom tool"}
              </button>
            </div>
          )}
        </motion.div>
      )}

      <ConnectToolModal
        tool={pendingConnect}
        connecting={connecting === pendingConnect?.name}
        onConnect={confirmConnect}
        onClose={() => setPendingConnect(null)}
      />
    </AnimatePresence>
  );
}
