import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, Plus, FileUp, Loader2, Check, Link2, Paperclip, X, Bot } from "lucide-react";
import { CATALOG } from "@/lib/toolCatalog";
import { getAllConnections, subscribeConnections } from "@/lib/connectionsStore";
import { connectTool } from "@/lib/connectService";
import { aura } from "@/api/auraClient";
import { listAgentConnections } from "@/lib/auraApi";
import AgentConnectionForm from "./AgentConnectionForm";

// Normal users only see tools with a backend-owned OAuth route. Custom API,
// MCP, key, and browser provisioning remains an operator-side concern.

export default function ResourceComposer({ open, onClose, onAddTool, onAddAgent, onAddDocument, pinnedTools = [], pinnedDocs = [] }) {
  const [tab, setTab] = useState("tools");
  const [query, setQuery] = useState("");
  const [connecting, setConnecting] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [connections, setConnections] = useState(getAllConnections);
  const [connectionError, setConnectionError] = useState("");
  const [agents, setAgents] = useState([]);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [showAgentForm, setShowAgentForm] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => subscribeConnections(setConnections), []);

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    const refreshAgents = () => {
      setLoadingAgents(true);
      listAgentConnections()
        .then((items) => {
          if (active) setAgents(items.filter((agent) => agent.enabled && agent.status === "verified"));
        })
        .catch((error) => {
          if (active) setConnectionError(error?.message || "AURA could not load connected agents.");
        })
        .finally(() => {
          if (active) setLoadingAgents(false);
        });
    };
    refreshAgents();
    window.addEventListener("aura:agent-connected", refreshAgents);
    return () => {
      active = false;
      window.removeEventListener("aura:agent-connected", refreshAgents);
    };
  }, [open]);

  const q = query.trim().toLowerCase();
  const filtered = CATALOG.filter((t) => t.name.toLowerCase().includes(q));

  // One selection is one connection action: AURA opens the provider consent
  // page immediately and performs discovery/verification itself.
  const select = async (name) => {
    if (pinnedTools.includes(name)) return;
    onAddTool(name);
    if (!connections[name]) await connectOne(name);
  };

  const connectOne = async (name) => {
    setConnecting(name);
    setConnectionError("");
    try {
      await connectTool(name);
    } catch (error) {
      setConnectionError(error?.message || `AURA couldn't connect ${name}.`);
    } finally {
      setConnecting(null);
    }
  };

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (pinnedDocs.length >= 8) {
      setUploadError("Attach no more than eight documents to one workflow.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setUploadError("Choose a file smaller than 10 MB.");
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    setUploading(true);
    setUploadError("");
    try {
      const out = await aura.integrations.Core.UploadFile({ file });
      onAddDocument({ name: file.name, file_url: out.file_url, size: file.size });
    } catch (cause) {
      setUploadError(cause.message || "AURA could not attach that file.");
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
          className="absolute bottom-full mb-2 left-0 z-30 w-[min(420px,calc(100vw-2rem))] bg-card border border-white/10 rounded-xl shadow-2xl overflow-hidden"
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
              onClick={() => setTab("agents")}
              className={`flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg font-medium transition-all ${tab === "agents" ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-white/5"}`}
            >
              <Bot className="w-3 h-3" /> Agents
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
                  placeholder="Search verified connectors..."
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
                                onClick={() => connectOne(t.name)}
                                disabled={isConnecting}
                                className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md text-amber-400 hover:bg-amber-400/10 transition-colors"
                              >
                                {isConnecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                                {isConnecting ? "Connecting…" : "Connect"}
                              </button>
                            )}
                          </>
                        ) : (
                          <button
                            onClick={() => select(t.name)}
                            disabled={isConnecting}
                            className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-md text-primary hover:bg-primary/10 transition-colors shrink-0"
                          >
                            {isConnecting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                            {isConnecting ? "Connecting…" : isConnected ? "Select" : "Connect"}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}

                {!filtered.length && (
                  <p className="text-center text-[10px] text-muted-foreground/60 py-6">No verified one-click connector found</p>
                )}
                {connectionError && <p className="px-2 py-2 text-[10px] leading-relaxed text-red-300">{connectionError}</p>}
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
              {uploadError && <p className="mt-2 text-[10px] text-red-400">{uploadError}</p>}

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

          {tab === "agents" && (
            <div className="max-h-[440px] overflow-y-auto p-3">
              {loadingAgents ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-5 w-5 animate-spin text-primary" />
                </div>
              ) : showAgentForm || agents.length === 0 ? (
                <AgentConnectionForm
                  onConnected={(agent) => {
                    setAgents((current) => [
                      ...current.filter((item) => item.id !== agent.id),
                      agent,
                    ]);
                    onAddAgent?.(agent.name);
                    setShowAgentForm(false);
                  }}
                />
              ) : (
                <div className="space-y-2">
                  <div className="mb-3">
                    <h3 className="text-sm font-semibold">Connected agents</h3>
                    <p className="mt-1 text-[11px] text-muted-foreground">Select an agent for this workflow, or connect another one.</p>
                  </div>
                  {agents.map((agent) => {
                    const selected = pinnedTools.includes(agent.name);
                    return (
                      <div key={agent.id} className="flex items-center gap-2 rounded-lg border border-white/8 p-2">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                          <Bot className="h-4 w-4 text-primary" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[11px] font-medium">{agent.name}</p>
                          <p className="truncate text-[10px] text-muted-foreground">{String(agent.protocol || "agent").toUpperCase()} · {agent.owner}</p>
                        </div>
                        <button
                          type="button"
                          disabled={selected}
                          onClick={() => onAddAgent?.(agent.name)}
                          className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-primary hover:bg-primary/10 disabled:text-emerald-400"
                        >
                          {selected ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
                          {selected ? "Selected" : "Select"}
                        </button>
                      </div>
                    );
                  })}
                  <button
                    type="button"
                    onClick={() => setShowAgentForm(true)}
                    className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-primary/25 py-2 text-[11px] font-medium text-primary hover:bg-primary/10"
                  >
                    <Plus className="h-3.5 w-3.5" /> Connect another agent
                  </button>
                </div>
              )}
              {connectionError && <p className="mt-2 px-2 py-2 text-[10px] leading-relaxed text-red-300">{connectionError}</p>}
            </div>
          )}

        </motion.div>
      )}
    </AnimatePresence>
  );
}
