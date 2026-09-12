import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  Check,
  FileUp,
  Link2,
  Loader2,
  Paperclip,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  X,
} from "lucide-react";

import { aura } from "@/api/auraClient";
import { getAllConnections, subscribeConnections } from "@/lib/connectionsStore";
import {
  connectTool,
  disconnectTool,
  getToolConnection,
  hydrateConnections,
  reconnectTool,
  testToolConnection,
} from "@/lib/connectService";
import {
  attachDocument,
  getAttachedDocuments,
  removeDocument,
  subscribeDocuments,
} from "@/lib/documentStore";
import { requestManagedConnector, searchConnectorBrokerApps } from "@/lib/auraApi";
import {
  CATALOG,
  mergeMarketplaceApps,
  searchMarketplace,
} from "@/lib/toolCatalog";

const isAura = (name) => name === "AURA Intelligence";

export default function ConnectionsPill() {
  const [connected, setConnected] = useState(getAllConnections);
  const [documents, setDocuments] = useState(getAttachedDocuments);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [tab, setTab] = useState("apps");
  const [query, setQuery] = useState("");
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [connecting, setConnecting] = useState(null);
  const [requesting, setRequesting] = useState(null);
  const [searchingCatalog, setSearchingCatalog] = useState(false);
  const [catalogSearchQuery, setCatalogSearchQuery] = useState("");
  const [connectionAction, setConnectionAction] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [managedConnection, setManagedConnection] = useState(null);
  const fileRef = useRef(null);

  useEffect(() => {
    const unsubscribeConnections = subscribeConnections(setConnected);
    const unsubscribeDocuments = subscribeDocuments(setDocuments);
    hydrateConnections()
      .then(() => setCatalogRevision((value) => value + 1))
      .catch((cause) => setError(cause.message));
    return () => {
      unsubscribeConnections();
      unsubscribeDocuments();
    };
  }, []);

  useEffect(() => {
    const normalized = query.trim().replace(/\s+/g, " ");
    if (normalized.length < 2) {
      setSearchingCatalog(false);
      setCatalogSearchQuery("");
      return undefined;
    }
    let cancelled = false;
    setSearchingCatalog(true);
    const timer = window.setTimeout(() => {
      searchConnectorBrokerApps(normalized)
        .then((result) => {
          if (cancelled) return;
          mergeMarketplaceApps(result.apps);
          setCatalogRevision((value) => value + 1);
          setCatalogSearchQuery(normalized);
          setError("");
        })
        .catch(() => {
          if (!cancelled) setError("AURA could not search the app network. Try again in a moment.");
        })
        .finally(() => {
          if (!cancelled) setSearchingCatalog(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const connectedTools = useMemo(() => {
    const catalogConnected = CATALOG.filter((tool) => connected[tool.name] && !isAura(tool.name));
    const catalogNames = new Set(CATALOG.map((tool) => tool.name.toLowerCase()));
    const existingConnections = Object.keys(connected)
      .filter((name) => !isAura(name) && !catalogNames.has(name.toLowerCase()))
      .map((name) => ({ name, icon: "🔗", desc: "Existing workspace connection" }));
    return [...catalogConnected, ...existingConnections];
  }, [connected, catalogRevision]);

  const marketplace = useMemo(() => {
    return searchMarketplace(query);
  }, [query, catalogRevision]);

  const count = connectedTools.length;
  const stacked = connectedTools.slice(0, 4);

  const connect = async (tool) => {
    if (!tool.connectable || connected[tool.name]) return;
    setConnecting(tool.name);
    setError("");
    try {
      await connectTool(tool.name);
      await hydrateConnections();
    } catch (cause) {
      setError(cause.message || `Could not connect ${tool.name}.`);
    } finally {
      setConnecting(null);
    }
  };

  const requestApp = async (tool) => {
    setRequesting(tool.name);
    setError("");
    try {
      await requestManagedConnector(tool.name);
      await hydrateConnections();
      setCatalogRevision((value) => value + 1);
    } catch (cause) {
      setError(cause.message || `AURA could not request ${tool.name}.`);
    } finally {
      setRequesting(null);
    }
  };

  const openConnectionManager = async (name) => {
    setConnectionAction(name);
    setError("");
    try {
      const connection = await getToolConnection(name);
      if (!connection) throw new Error(`${name} is not connected.`);
      setManagedConnection({ ...connection, uiName: name });
    } catch (cause) {
      setError(cause.message || `Could not load ${name}.`);
    } finally {
      setConnectionAction("");
    }
  };

  const runConnectionAction = async (name, action) => {
    setConnectionAction(name);
    setError("");
    try {
      if (action === "disconnect") {
        await disconnectTool(name, managedConnection?.id);
        setManagedConnection(null);
      } else if (action === "reconnect") {
        const result = await reconnectTool(name, managedConnection?.id);
        setManagedConnection({ ...result.tool, uiName: name });
      } else {
        await testToolConnection(name, managedConnection?.id);
      }
    } catch (cause) {
      setError(cause.message || `Could not ${action} ${name}.`);
    } finally {
      setConnectionAction("");
    }
  };

  const handleFiles = async (event) => {
    const files = [...(event.target.files || [])];
    if (!files.length) return;
    if (files.length + documents.length > 8) {
      setError("Attach no more than eight documents to one workflow.");
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    if (files.some((file) => file.size > 10 * 1024 * 1024)) {
      setError("Each document must be smaller than 10 MB.");
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    setUploading(true);
    setError("");
    try {
      for (const file of files) {
        const result = await aura.integrations.Core.UploadFile({ file });
        attachDocument({ name: file.name, file_url: result.file_url, size: file.size });
      }
    } catch (cause) {
      setError(cause.message || "AURA could not attach that document.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const openConnect = (nextTab = "apps") => {
    setTab(nextTab);
    setQuery("");
    setConnectOpen(true);
  };

  const closeWorkspace = () => {
    setConnectOpen(false);
    setWorkspaceOpen(false);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setWorkspaceOpen(true)}
        className="flex items-center gap-2 rounded-full border border-white/8 py-1 pl-1.5 pr-3 transition-all hover:border-white/15 hover:bg-white/5"
      >
        <div className="flex items-center">
          {stacked.map((tool, index) => (
            <div
              key={tool.name}
              style={{ marginLeft: index === 0 ? 0 : -8, zIndex: stacked.length - index }}
              className="flex h-6 w-6 items-center justify-center rounded-full border border-white/10 bg-secondary text-[11px]"
            >
              {tool.icon}
            </div>
          ))}
        </div>
        <Link2 className="h-3.5 w-3.5 text-muted-foreground/70" />
        <span className="text-xs font-medium text-foreground/90">Connect</span>
        <span className="text-xs text-muted-foreground/60">{count}</span>
      </button>

      <AnimatePresence>
        {workspaceOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              onClick={closeWorkspace}
              className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
            />
            <motion.aside
              initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-white/6 bg-card shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-white/6 px-5 py-4">
                <div className="flex items-center gap-2">
                  <div className="rounded-lg border border-primary/20 bg-primary/10 p-1.5"><Link2 className="h-4 w-4 text-primary" /></div>
                  <span className="text-sm font-semibold">Your workspace</span>
                </div>
                <button type="button" aria-label="Close workspace" onClick={closeWorkspace} className="rounded-lg p-1.5 text-muted-foreground hover:bg-white/5 hover:text-foreground"><X className="h-4 w-4" /></button>
              </div>

              <div className="px-5 py-3">
                <p className="text-xs text-muted-foreground">AURA owns setup and verification. You only approve the provider’s official consent window.</p>
                {error && <p className="mt-2 rounded-lg border border-red-400/20 bg-red-400/5 p-2 text-xs text-red-400">{error}</p>}
              </div>

              <div className="flex-1 space-y-4 overflow-y-auto px-3 pb-4">
                <section>
                  <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Connected apps</p>
                  {connectedTools.length ? connectedTools.map((tool) => (
                    <div key={tool.name} className="flex items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-white/5">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/8 bg-secondary text-base">{tool.icon}</div>
                      <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{tool.name}</p><p className="truncate text-xs text-muted-foreground">{tool.desc}</p></div>
                      <button type="button" onClick={() => openConnectionManager(tool.name)} disabled={connectionAction === tool.name} className="flex items-center gap-1 px-1.5 py-1 text-[10px] text-muted-foreground hover:text-foreground">
                        {connectionAction === tool.name ? <Loader2 className="h-3 w-3 animate-spin" /> : <Settings2 className="h-3 w-3" />}
                        Manage
                      </button>
                      <Check className="h-3.5 w-3.5 text-emerald-400" />
                    </div>
                  )) : <p className="px-2 py-3 text-xs text-muted-foreground">No apps connected yet.</p>}
                </section>

                <section>
                  <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Attached documents</p>
                  {documents.length ? documents.map((document) => (
                    <div key={document.file_url} className="flex items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-white/5">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/8 bg-secondary"><Paperclip className="h-4 w-4 text-primary" /></div>
                      <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{document.name}</p><p className="text-xs text-muted-foreground">Available to the next workflow</p></div>
                      <button type="button" aria-label={`Remove ${document.name}`} onClick={() => removeDocument(document.file_url)} className="p-1.5 text-muted-foreground hover:text-red-400"><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  )) : <p className="px-2 py-3 text-xs text-muted-foreground">No documents attached yet.</p>}
                </section>
              </div>

              <div className="grid grid-cols-2 gap-2 border-t border-white/6 px-5 py-4">
                <button type="button" onClick={() => openConnect("apps")} className="flex items-center justify-center gap-1.5 rounded-xl border border-primary/30 py-2.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"><Plus className="h-3.5 w-3.5" />Find apps</button>
                <button type="button" onClick={() => openConnect("documents")} className="flex items-center justify-center gap-1.5 rounded-xl border border-white/10 py-2.5 text-sm font-medium transition-colors hover:bg-white/5"><Paperclip className="h-3.5 w-3.5" />Attach docs</button>
              </div>
            </motion.aside>
          </>
        )}

        {connectOpen && (
          <>
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setConnectOpen(false)} className="fixed inset-0 z-[55] bg-black/30 backdrop-blur-sm" />
            <motion.aside
              initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
              transition={{ type: "spring", stiffness: 300, damping: 30 }}
              className="fixed right-0 top-0 z-[60] flex h-full w-full max-w-md flex-col border-l border-white/6 bg-card shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-white/6 px-5 py-4">
                <div className="flex items-center gap-2">
                  <button type="button" aria-label="Return to workspace" onClick={() => setConnectOpen(false)} className="-ml-1.5 rounded-lg p-1.5 text-muted-foreground hover:bg-white/5 hover:text-foreground"><ArrowLeft className="h-4 w-4" /></button>
                  <span className="text-sm font-semibold">Connect resources</span>
                </div>
                <button type="button" aria-label="Close connections" onClick={closeWorkspace} className="rounded-lg p-1.5 text-muted-foreground hover:bg-white/5 hover:text-foreground"><X className="h-4 w-4" /></button>
              </div>

              <div className="flex gap-1 border-b border-white/6 px-5 pt-3">
                <button type="button" onClick={() => setTab("apps")} className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium ${tab === "apps" ? "border-primary text-primary" : "border-transparent text-muted-foreground"}`}><Link2 className="h-3.5 w-3.5" />Apps</button>
                <button type="button" onClick={() => setTab("documents")} className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium ${tab === "documents" ? "border-primary text-primary" : "border-transparent text-muted-foreground"}`}><Paperclip className="h-3.5 w-3.5" />Documents</button>
              </div>

              {error && <p className="mx-5 mt-3 rounded-lg border border-red-400/20 bg-red-400/5 p-2 text-xs text-red-400">{error}</p>}

              {tab === "apps" ? (
                <>
                  <div className="px-5 py-4">
                    <h3 className="text-base font-semibold">App marketplace</h3>
                    <p className="mt-1 text-xs text-muted-foreground">Search apps and APIs across AURA’s embedded connector network. You only approve the provider’s consent screen.</p>
                  </div>
                  <div className="px-5 pb-3">
                    <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-card/70 px-3 py-2">
                      <Search className="h-3.5 w-3.5 text-muted-foreground/60" />
                      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search apps and categories…" className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/40" />
                      {searchingCatalog && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
                    </div>
                  </div>
                  <div className="flex-1 space-y-1 overflow-y-auto px-3 pb-4">
                    {marketplace.map((tool) => {
                      const isConnected = Boolean(connected[tool.name]);
                      return (
                        <div key={`${tool.provider}:${tool.name}`} className="flex items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-white/5">
                          <div className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-lg border border-white/8 bg-secondary text-base">
                            {tool.logoUrl ? <img src={tool.logoUrl} alt="" className="h-6 w-6 object-contain" /> : tool.icon}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium">{tool.name}</p>
                            <p className="truncate text-xs text-muted-foreground">{tool.desc}</p>
                          </div>
                          {isConnected ? (
                            <span className="flex items-center gap-1 text-xs text-emerald-400"><Check className="h-3.5 w-3.5" />Connected</span>
                          ) : tool.requestable && catalogSearchQuery !== query.trim().replace(/\s+/g, " ") ? (
                            searchingCatalog
                              ? <span className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Searching…</span>
                              : <span className="rounded-full border border-amber-400/20 bg-amber-400/5 px-2 py-1 text-[10px] text-amber-300">Coming soon</span>
                          ) : tool.requestable ? (
                            <button type="button" onClick={() => requestApp(tool)} disabled={requesting === tool.name} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50">
                              {requesting === tool.name ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}{requesting === tool.name ? "Requesting…" : "Request app"}
                            </button>
                          ) : tool.connectable ? (
                            <button type="button" onClick={() => connect(tool)} disabled={Boolean(connecting)} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50">
                              {connecting === tool.name ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}{connecting === tool.name ? "Opening…" : "Connect"}
                            </button>
                          ) : (
                            <span className="rounded-full border border-amber-400/20 bg-amber-400/5 px-2 py-1 text-[10px] text-amber-300">{tool.availability === "requested" ? "Requested" : "Coming soon"}</span>
                          )}
                        </div>
                      );
                    })}
                    {!marketplace.length && <p className="py-8 text-center text-xs text-muted-foreground">Type at least two characters to find or request an app.</p>}
                  </div>
                </>
              ) : (
                <div className="flex-1 overflow-y-auto p-5">
                  <h3 className="text-base font-semibold">Attach documents</h3>
                  <p className="mt-1 text-xs text-muted-foreground">Files uploaded here are available to the next workflow without leaving Connect.</p>
                  <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading} className="mt-4 flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/12 py-8 transition-all hover:border-primary/30 hover:bg-primary/5 disabled:opacity-50">
                    {uploading ? <Loader2 className="h-6 w-6 animate-spin text-primary" /> : <FileUp className="h-6 w-6 text-primary" />}
                    <span className="text-sm font-medium">{uploading ? "Uploading…" : "Choose documents"}</span>
                    <span className="text-[11px] text-muted-foreground">PDF, DOC, sheet, CSV, image, or other workflow input</span>
                  </button>
                  <input ref={fileRef} type="file" multiple className="hidden" onChange={handleFiles} />
                  <div className="mt-4 space-y-1">
                    {documents.map((document) => (
                      <div key={document.file_url} className="flex items-center gap-3 rounded-xl bg-white/5 p-2.5">
                        <Paperclip className="h-4 w-4 shrink-0 text-primary" />
                        <p className="min-w-0 flex-1 truncate text-sm">{document.name}</p>
                        <Check className="h-3.5 w-3.5 text-emerald-400" />
                        <button type="button" aria-label={`Remove ${document.name}`} onClick={() => removeDocument(document.file_url)} className="p-1 text-muted-foreground hover:text-red-400"><X className="h-3.5 w-3.5" /></button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {managedConnection && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-[80] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
            onClick={() => setManagedConnection(null)}
          >
            <motion.div
              initial={{ scale: 0.97, y: 8 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.97, y: 8 }}
              onClick={(event) => event.stopPropagation()}
              className="w-full max-w-sm overflow-hidden rounded-2xl border border-white/10 bg-card shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-white/8 px-5 py-4">
                <p className="text-sm font-semibold">{managedConnection.uiName || managedConnection.display_name}</p>
                <button type="button" aria-label="Close connection manager" onClick={() => setManagedConnection(null)} className="p-1.5 text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
              </div>
              <div className="px-6 py-6">
                <div className="flex items-center gap-3 rounded-xl border border-emerald-400/15 bg-emerald-400/5 px-4 py-3">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-400/15"><Check className="h-4 w-4 text-emerald-400" /></div>
                  <div><p className="text-xs font-medium text-emerald-400">Connected and verified</p><p className="mt-0.5 text-[11px] text-muted-foreground">Ready to use in plans you approve.</p></div>
                </div>
                {error && <p className="mt-4 rounded-lg border border-red-400/20 bg-red-400/5 p-2 text-xs text-red-400">{error}</p>}
              </div>
              <div className="grid grid-cols-3 gap-2 border-t border-white/8 p-4">
                <button type="button" onClick={() => runConnectionAction(managedConnection.uiName, "test")} disabled={connectionAction === managedConnection.uiName} className="flex items-center justify-center gap-1.5 rounded-lg border border-white/10 px-2 py-2.5 text-xs font-medium hover:bg-white/5"><Check className="h-3.5 w-3.5" />Test</button>
                <button type="button" onClick={() => runConnectionAction(managedConnection.uiName, "reconnect")} disabled={connectionAction === managedConnection.uiName} className="flex items-center justify-center gap-1.5 rounded-lg bg-primary px-2 py-2.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"><RefreshCw className="h-3.5 w-3.5" />Reconnect</button>
                <button type="button" onClick={() => runConnectionAction(managedConnection.uiName, "disconnect")} disabled={connectionAction === managedConnection.uiName} className="flex items-center justify-center gap-1.5 rounded-lg border border-red-400/30 px-2 py-2.5 text-xs font-medium text-red-400 hover:bg-red-400/10"><Trash2 className="h-3.5 w-3.5" />Remove</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
