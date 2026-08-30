import { useState, useMemo, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Link2, Plus, Search, X, ArrowLeft, Check, ScanSearch, Trash2, Loader2, Settings2, RefreshCw } from "lucide-react";

import { getAllConnections, subscribeConnections } from "@/lib/connectionsStore";
import { connectTool, disconnectTool, getToolConnection, hasStandardOAuth, hydrateConnections, reconnectTool, recordInterfaceConnection, testToolConnection } from "@/lib/connectService";
import { CATALOG } from "@/lib/toolCatalog";
import AuraInterfaceConnect from "./AuraInterfaceConnect";
import ConnectToolModal from "./ConnectToolModal";

// Tool catalog lives in @/lib/toolCatalog so the plan-stage tool picker and
// this connections panel share one source of truth.

const isAura = (n) => n === "AURA Intelligence";

export default function ConnectionsPill() {
  const [connected, setConnected] = useState(getAllConnections);
  useEffect(() => subscribeConnections(setConnected), []);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [interfaceTool, setInterfaceTool] = useState(null);
  const [pendingConnect, setPendingConnect] = useState(null);
  const [error, setError] = useState("");
  const [connectionAction, setConnectionAction] = useState("");
  const [managedConnection, setManagedConnection] = useState(null);

  useEffect(() => {
    hydrateConnections().catch((e) => setError(e.message));
  }, []);

  const connectedTools = useMemo(() => {
    const catalogConnected = CATALOG.filter((t) => connected[t.name] && !isAura(t.name));
    const catalogNames = new Set(CATALOG.map((t) => t.name.toLowerCase()));
    // Custom tools learned through the AURA Interface flow are in the store
    // but not in the static catalog — show them in the workspace list too.
    const customConnected = Object.keys(connected)
      .filter((n) => !isAura(n) && !catalogNames.has(n.toLowerCase()))
      .map((n) => ({ name: n, icon: "🔗", interface: true, desc: "Connected through AURA Interface" }));
    return [...catalogConnected, ...customConnected];
  }, [connected]);
  const availableTools = useMemo(
    () => CATALOG.filter((t) => !connected[t.name] && !isAura(t.name)),
    [connected]
  );

  const count = connectedTools.length;
  const stacked = connectedTools.slice(0, 4);
  const filtered = availableTools.filter((t) =>
    t.name.toLowerCase().includes(query.trim().toLowerCase())
  );

  const [connecting, setConnecting] = useState(null);
  const connect = async (name, opts = {}) => {
    setConnecting(name);
    setError("");
    try {
      const res = await connectTool(name, opts);
      if (res.interfaceTool) setInterfaceTool(res.interfaceTool);
      if (res.needsConfiguration) setPendingConnect({ name, custom: true, desc: "" });
      if (res.connected) await hydrateConnections();
    } catch (e) {
      setError(e.message || `Could not connect ${name}.`);
    } finally {
      setConnecting(null);
    }
  };

  const confirmConnect = async (toolObj) => {
    if (!pendingConnect) return;
    const name = toolObj?.name || pendingConnect.name;
    await connect(name, {
      apiKey: toolObj?.apiKey,
      baseUrl: toolObj?.baseUrl,
      connectionKind: toolObj?.connectionKind,
      credentials: toolObj?.credentials,
      authorizationUrl: toolObj?.authorizationUrl,
      tokenUrl: toolObj?.tokenUrl,
      clientId: toolObj?.clientId,
      clientSecret: toolObj?.clientSecret,
      scopes: toolObj?.scopes,
      allowedOperations: toolObj?.connectionKind === "mcp" ? ["mcp.call"] : ["http.request"],
    });
    setPendingConnect(null);
  };

  const openConnectionManager = async (name) => {
    setConnectionAction(name);
    setError("");
    try {
      const connection = await getToolConnection(name);
      if (!connection) throw new Error(`${name} is not connected.`);
      setManagedConnection({ ...connection, uiName: name });
    } catch (e) {
      setError(e.message || `Could not load ${name}.`);
    } finally {
      setConnectionAction("");
    }
  };

  const runConnectionAction = async (name, action) => {
    setConnectionAction(name);
    setError("");
    try {
      if (action === "disconnect") {
        await disconnectTool(name);
        setManagedConnection(null);
      } else if (action === "reconnect") {
        const result = await reconnectTool(name);
        setManagedConnection({ ...result.tool, uiName: name });
      } else {
        await testToolConnection(name);
        const refreshed = await getToolConnection(name);
        if (refreshed) setManagedConnection({ ...refreshed, uiName: name });
      }
    } catch (e) {
      setError(e.message || `Could not ${action} ${name}.`);
    } finally {
      setConnectionAction("");
    }
  };

  const q = query.trim();
  const canAddCustom = q.length > 0 && !CATALOG.some((t) => t.name.toLowerCase() === q.toLowerCase());

  return (
    <>
      {/* Pill trigger */}
      <button
        onClick={() => setWorkspaceOpen(true)}
        className="flex items-center gap-2 pl-1.5 pr-3 py-1 rounded-full border border-white/8 hover:border-white/15 hover:bg-white/5 transition-all"
      >
        <div className="flex items-center">
          {stacked.map((t, i) => (
            <div
              key={t.name}
              style={{ marginLeft: i === 0 ? 0 : -8, zIndex: stacked.length - i }}
              className="w-6 h-6 rounded-full bg-secondary border border-white/10 flex items-center justify-center text-[11px]"
            >
              {t.icon}
            </div>
          ))}
        </div>
        <Link2 className="w-3.5 h-3.5 text-muted-foreground/70" />
        <span className="text-xs font-medium text-foreground/90">Connections</span>
        <span className="text-xs text-muted-foreground/60">{count}</span>
      </button>

      <AnimatePresence>
        {workspaceOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setWorkspaceOpen(false)}
              className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
            />
            <motion.aside
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="fixed right-0 top-0 h-full w-full max-w-md z-50 bg-card border-l border-white/6 flex flex-col shadow-2xl"
            >
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-white/6">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
                    <Plus className="w-4 h-4 text-primary" />
                  </div>
                  <span className="font-semibold text-sm">Your workspace</span>
                </div>
                <button onClick={() => setWorkspaceOpen(false)} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="px-5 py-3">
                <p className="text-xs text-muted-foreground">Give AURA access to the tools you want it to work with.</p>
                {error && <p className="mt-2 text-xs text-red-400 rounded-lg border border-red-400/20 bg-red-400/5 p-2">{error}</p>}
              </div>

              {/* Connected list */}
              <div className="px-3 flex-1 space-y-1 overflow-y-auto">
                {connectedTools.map((t) => (
                  <div key={t.name} className="flex items-center gap-3 p-2.5 rounded-xl hover:bg-white/5 transition-colors">
                    <div className="w-9 h-9 rounded-lg bg-secondary border border-white/8 flex items-center justify-center text-base">
                      {t.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{t.name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {t.interface ? "Connected through AURA Interface" : t.desc}
                      </p>
                    </div>
                    <button onClick={() => openConnectionManager(t.name)} disabled={connectionAction === t.name} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground px-1.5 py-1">
                      {connectionAction === t.name ? <Loader2 className="w-3 h-3 animate-spin" /> : <Settings2 className="w-3 h-3" />}
                      Manage
                    </button>
                    <button onClick={() => runConnectionAction(t.name, "disconnect")} disabled={connectionAction === t.name} title="Revoke access" className="p-1.5 text-muted-foreground hover:text-red-400">
                      {connectionAction === t.name ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                    </button>
                    <div className="flex items-center gap-1 text-emerald-400">
                      <Check className="w-3.5 h-3.5" />
                    </div>
                  </div>
                ))}

                <button
                  onClick={() => setPendingConnect({ name: "", custom: true, interface: true, desc: "" })}
                  className="w-full flex items-center gap-3 p-2.5 rounded-xl border border-dashed border-white/10 hover:border-primary/30 hover:bg-primary/5 transition-colors text-left"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">Add a custom tool</p>
                    <p className="text-xs text-muted-foreground truncate">A tool you use at work that isn't listed</p>
                  </div>
                </button>
              </div>

              {/* Footer */}
              <div className="px-5 py-4 border-t border-white/6">
                <button
                  onClick={() => { setConnectOpen(true); setQuery(""); }}
                  className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl border border-primary/30 text-primary hover:bg-primary/10 transition-colors text-sm font-medium"
                >
                  <Plus className="w-3.5 h-3.5" />
                  + Connect more
                </button>
              </div>
            </motion.aside>
          </>
        )}

        {connectOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setConnectOpen(false)}
              className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
            />
            <motion.aside
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="fixed right-0 top-0 h-full w-full max-w-md z-50 bg-card border-l border-white/6 flex flex-col shadow-2xl"
            >
              {/* Header with back */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-white/6">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setConnectOpen(false)}
                    className="p-1.5 -ml-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <ArrowLeft className="w-4 h-4" />
                  </button>
                  <span className="font-semibold text-sm">Your workspace</span>
                </div>
                <button onClick={() => setConnectOpen(false)} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="px-5 py-4">
                <div className="flex items-center gap-2 mb-1">
                  <Search className="w-4 h-4 text-primary" />
                  <h3 className="text-base font-semibold">What do you want to connect?</h3>
                </div>
                <p className="text-xs text-muted-foreground">Search a tool, or paste a URL for one AURA doesn't know yet.</p>
              </div>

              <div className="px-5 pb-3">
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-card/70 border border-white/10">
                  <Search className="w-3.5 h-3.5 text-muted-foreground/60" />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search or type a tool..."
                    className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground/40"
                  />
                </div>
              </div>

              <div className="px-3 pb-4 flex-1 space-y-1 overflow-y-auto">
                {filtered.map((t) => (
                  <div key={t.name} className="flex items-center gap-3 p-2.5 rounded-xl hover:bg-white/5 transition-colors">
                    <div className="w-9 h-9 rounded-lg bg-secondary border border-white/8 flex items-center justify-center text-base">
                      {t.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{t.name}</p>
                      <p className="text-xs text-muted-foreground truncate">{t.desc}</p>
                    </div>
                    <button
                      onClick={() => (t.apiKey || !hasStandardOAuth(t.name) ? setPendingConnect({ ...t, custom: true }) : connect(t.name))}
                      disabled={connecting === t.name}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-primary hover:bg-primary/10 transition-colors text-xs font-medium disabled:opacity-50"
                    >
                      {t.interface ? <ScanSearch className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
                      {connecting === t.name ? "Connecting…" : t.interface ? "Connect tool" : "Connect"}
                    </button>
                  </div>
                ))}

                {canAddCustom && (
                  <>
                    {filtered.length > 0 && <div className="h-px bg-white/6 my-1" />}
                    <button
                      onClick={() => setPendingConnect({ name: q, custom: true, interface: true, desc: "" })}
                      className="w-full flex items-center gap-3 p-2.5 rounded-xl hover:bg-primary/10 transition-colors text-left"
                    >
                      <div className="w-9 h-9 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0">
                        <Plus className="w-4 h-4 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">Connect “{q}”</p>
                        <p className="text-xs text-muted-foreground truncate">Custom tool you use at work — AURA learns its interface</p>
                      </div>
                    </button>
                  </>
                )}

                {filtered.length === 0 && !canAddCustom && (
                  <p className="text-center text-xs text-muted-foreground py-8">All tools connected</p>
                )}
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <AuraInterfaceConnect
        open={!!interfaceTool}
        toolName={interfaceTool}
        onClose={() => setInterfaceTool(null)}
        onConnect={async (name, meta) => {
          try {
            setError("");
            await recordInterfaceConnection(name, meta);
            await hydrateConnections();
            setInterfaceTool(null);
          } catch (e) {
            setError(e.message || "This web application could not be connected.");
          }
        }}
      />

      <AnimatePresence>
        {managedConnection && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-[80] bg-black/65 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setManagedConnection(null)}>
            <motion.div initial={{ scale: 0.97, y: 8 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.97, y: 8 }} onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-2xl border border-white/10 bg-card shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between px-5 py-4 border-b border-white/8">
                <p className="text-sm font-semibold">{managedConnection.uiName || managedConnection.display_name}</p>
                <button onClick={() => setManagedConnection(null)} className="p-1.5 text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
              </div>
              <div className="px-6 py-6">
                <div className="flex items-center gap-3 rounded-xl border border-emerald-400/15 bg-emerald-400/5 px-4 py-3">
                  <div className="w-7 h-7 rounded-full bg-emerald-400/15 flex items-center justify-center shrink-0">
                    <Check className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-emerald-400">Connected</p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">Ready to use in plans you approve.</p>
                  </div>
                </div>
                {error && <p className="mt-4 text-xs text-red-400 rounded-lg border border-red-400/20 bg-red-400/5 p-2">{error}</p>}
              </div>
              <div className="p-4 border-t border-white/8">
                <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Connection actions</p>
                <div className="grid grid-cols-2 gap-2">
                  <button onClick={() => runConnectionAction(managedConnection.uiName, "reconnect")} disabled={managedConnection.kind !== "oauth" || connectionAction === managedConnection.uiName} className="flex items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"><RefreshCw className="w-3.5 h-3.5" /> Reconnect</button>
                  <button onClick={() => runConnectionAction(managedConnection.uiName, "disconnect")} disabled={connectionAction === managedConnection.uiName} className="flex items-center justify-center gap-1.5 rounded-lg border border-red-400/30 px-3 py-2.5 text-xs font-medium text-red-400 hover:bg-red-400/10"><Trash2 className="w-3.5 h-3.5" /> Disconnect</button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <ConnectToolModal
        tool={pendingConnect}
        connecting={connecting === pendingConnect?.name}
        onConnect={confirmConnect}
        onClose={() => setPendingConnect(null)}
      />
    </>
  );
}
