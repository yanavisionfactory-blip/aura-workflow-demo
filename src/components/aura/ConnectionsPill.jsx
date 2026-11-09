import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  Bot,
  Check,
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

import DocumentUpload from "./DocumentUpload";
import AgentConnectionForm from "./AgentConnectionForm";
import { agentConnectionPreset } from "@/lib/agentConnections.mjs";
import { connectionScreenPreset } from "@/lib/connectionNavigation.mjs";
import { connectionIsReady, isMetaConnection, metaConnectionRows } from "@/lib/metaConnectionRoutes.mjs";
import { getAllConnections, subscribeConnections } from "@/lib/connectionsStore";
import {
  connectTool,
  chooseGoogleAdsAccount,
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
import { listAgentConnections, requestManagedConnector, searchConnectorBrokerApps } from "@/lib/auraApi";
import {
  CATALOG,
  catalogEntryFor,
  mergeMarketplaceApps,
  searchMarketplace,
} from "@/lib/toolCatalog";

const isAura = (name) => name === "AURA Intelligence";

export default function ConnectionsPill() {
  const [preset] = useState(() => agentConnectionPreset(
    typeof window === "undefined" ? "" : window.location.search,
  ));
  const [appPreset] = useState(() => typeof window === "undefined"
    ? null : connectionScreenPreset(window.location.search));
  const [connected, setConnected] = useState(getAllConnections);
  const [documents, setDocuments] = useState(getAttachedDocuments);
  const [workspaceOpen, setWorkspaceOpen] = useState(Boolean(preset || appPreset));
  const [connectOpen, setConnectOpen] = useState(Boolean(preset || appPreset));
  const [tab, setTab] = useState(appPreset ? "apps" : preset ? "agents" : "apps");
  const [query, setQuery] = useState(appPreset?.query || "");
  const [catalogRevision, setCatalogRevision] = useState(0);
  const [connecting, setConnecting] = useState(null);
  const [requesting, setRequesting] = useState(null);
  const [searchingCatalog, setSearchingCatalog] = useState(false);
  const [catalogSearchQuery, setCatalogSearchQuery] = useState("");
  const [connectionAction, setConnectionAction] = useState("");
  const [error, setError] = useState("");
  const [managedConnection, setManagedConnection] = useState(null);
  const [agentConnections, setAgentConnections] = useState([]);
  const [savedTools, setSavedTools] = useState([]);
  const [connectionsLoaded, setConnectionsLoaded] = useState(false);

  const refreshConnections = useCallback(async (options) => {
    const [tools, agents] = await Promise.all([
      hydrateConnections(options),
      listAgentConnections(),
    ]);
    setSavedTools(tools);
    setConnectionsLoaded(true);
    setManagedConnection((current) => current
      ? { ...current, ...tools.find((tool) => tool.id === current.id) } : null);
    setAgentConnections(agents);
    setCatalogRevision((value) => value + 1);
    return tools;
  }, []);

  useEffect(() => {
    const unsubscribeConnections = subscribeConnections(setConnected);
    const unsubscribeDocuments = subscribeDocuments(setDocuments);
    refreshConnections().catch((cause) => setError(cause.message));
    const handleAgentConnected = () => {
      refreshConnections().catch((cause) => setError(cause.message));
    };
    window.addEventListener("aura:agent-connected", handleAgentConnected);
    return () => {
      unsubscribeConnections();
      unsubscribeDocuments();
      window.removeEventListener("aura:agent-connected", handleAgentConnected);
    };
  }, [refreshConnections]);

  useEffect(() => {
    const normalized = query.trim().replace(/\s+/g, " ");
    if (normalized.length < 2 && normalized.toLowerCase() !== "x") {
      setSearchingCatalog(false);
      setCatalogSearchQuery("");
      return undefined;
    }
    let cancelled = false;
    setSearchingCatalog(true);
    let timer;
    const search = (attempt = 0) => {
      searchConnectorBrokerApps(normalized)
        .then((result) => {
          if (cancelled) return;
          mergeMarketplaceApps(result.apps);
          setCatalogRevision((value) => value + 1);
          setCatalogSearchQuery(normalized);
          setError("");
          const preparing = result.apps.some((item) =>
            ["queued", "in_progress"].includes(item.certification_status)
          );
          if (preparing && attempt < 10) {
            timer = window.setTimeout(() => search(attempt + 1), 2000);
          } else {
            setSearchingCatalog(false);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setError("AURA could not search the app network. Try again in a moment.");
            setSearchingCatalog(false);
          }
        })
    };
    timer = window.setTimeout(search, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const connectedTools = useMemo(() => {
    const catalogConnected = metaConnectionRows(CATALOG, savedTools, { includeSaved: true })
      .filter((tool) => (tool.connectionId || (tool.isConnected ?? connected[tool.name])) && !isAura(tool.name));
    const catalogNames = new Set(CATALOG.map((tool) => tool.name.toLowerCase()));
    const agentNames = new Set(agentConnections.map((agent) => agent.name.toLowerCase()));
    const existingConnections = Object.keys(connected)
      .filter((name) => !isAura(name) && !catalogNames.has(name.toLowerCase()) && !catalogEntryFor(name) && !agentNames.has(name.toLowerCase()))
      .map((name) => ({ name, icon: "🔗", desc: "Existing workspace connection" }));
    return [...catalogConnected, ...existingConnections];
  }, [agentConnections, connected, catalogRevision, savedTools]);

  const marketplace = useMemo(() => {
    return metaConnectionRows(searchMarketplace(query), savedTools);
  }, [query, catalogRevision, savedTools]);

  const agentCards = agentConnections
    .filter((agent) => agent.enabled && agent.status === "verified"
      && !savedTools.some((tool) => tool.id === agent.id && isMetaConnection(tool)))
    .map((agent) => ({
      ...agent,
      icon: "🤖",
      desc: `${String(agent.protocol || "agent").toUpperCase()} · ${agent.owner}`,
    }));
  const count = connectedTools.length + agentCards.length;
  const stacked = [...connectedTools, ...agentCards].slice(0, 4);

  const connect = async (tool) => {
    if ((isMetaConnection(tool) && !connectionsLoaded) || !tool.connectable || tool.connectionId || (tool.isConnected ?? connected[tool.name])) return;
    setConnecting(tool.rowKey || tool.name);
    setError("");
    try {
      const result = await connectTool(tool.name, { provider: tool.provider });
      if (result.authorizationStarted) return;
      if (["google-ads", "reddit-ads"].includes(result.connection?.slug)) {
        setManagedConnection({ ...result.connection, uiName: tool.name });
      }
      await refreshConnections();
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
      await hydrateConnections({ force: true });
      setCatalogRevision((value) => value + 1);
    } catch (cause) {
      setError(cause.message || `AURA could not request ${tool.name}.`);
    } finally {
      setRequesting(null);
    }
  };

  const openConnectionManager = async (tool) => {
    const name = typeof tool === "string" ? tool : tool.name;
    setConnectionAction(name);
    setError("");
    try {
      const connection = await getToolConnection(name, tool.connectionId, tool.provider, { exactProvider: Boolean(tool.connectionId) });
      if (!connection) throw new Error(`${name} is not connected.`);
      setManagedConnection({ ...connection, ...(tool.connection || {}), uiName: name, uiLabel: tool.displayName || name });
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
      if (action === "account") {
        const updated = await chooseGoogleAdsAccount(managedConnection, { force: true });
        setManagedConnection(updated);
      } else if (action === "disconnect") {
        await disconnectTool(name, managedConnection?.id);
        setManagedConnection(null);
      } else if (action === "reconnect") {
        const result = await reconnectTool(name, managedConnection?.id);
        if (result.redirecting) return;
        setManagedConnection({ ...result.tool, uiName: name });
      } else {
        const result = await testToolConnection(name, managedConnection?.id);
        setManagedConnection((current) => current ? { ...current, status: result.status, verification: result.verification } : null);
        await refreshConnections({ force: true });
        if (result.status !== "verified" || result.verification?.ok !== true) {
          const reason = result.verification?.reason;
          throw new Error(reason === "google_docs_write_scope_not_configured"
            ? "AURA's Google connection is missing Drive file creation access in its app setup. An administrator must correct it; reconnecting your account will not fix this."
            : reason === "google_docs_write_permission_missing"
            ? "Google Docs cannot create files yet. Reconnect Google and grant Drive file creation access."
            : `AURA could not verify ${name}. Check the connection before using it.`);
        }
        return;
      }
      await refreshConnections();
    } catch (cause) {
      if (action === "test") {
        const unverified = (tool) => ({ ...tool, status: "unverified", verification: { ...tool.verification, ok: false } });
        setManagedConnection((current) => current?.id === managedConnection?.id ? unverified(current) : current);
        setSavedTools((current) => current.map((tool) => tool.id === managedConnection?.id ? unverified(tool) : tool));
      }
      setError(cause.message || `Could not ${action} ${name}.`);
    } finally {
      setConnectionAction("");
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
              key={tool.rowKey || tool.name}
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
                <p className="text-xs text-muted-foreground">AURA owns setup and verification. Approve provider consent or enter required credentials in the secure embedded form.</p>
                {error && <p className="mt-2 rounded-lg border border-red-400/20 bg-red-400/5 p-2 text-xs text-red-400">{error}</p>}
              </div>

              <div className="flex-1 space-y-4 overflow-y-auto px-3 pb-4">
                <section>
                  <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Saved app connections</p>
                  {connectedTools.length ? connectedTools.map((tool) => (
                    <div key={tool.rowKey || tool.name} className="flex items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-white/5">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/8 bg-secondary text-base">{tool.icon}</div>
                      <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{tool.displayName || tool.name}</p><p className="truncate text-xs text-muted-foreground">{tool.desc}</p></div>
                      <button type="button" onClick={() => openConnectionManager(tool)} disabled={connectionAction === tool.name} className="flex items-center gap-1 px-1.5 py-1 text-[10px] text-muted-foreground hover:text-foreground">
                        {connectionAction === tool.name ? <Loader2 className="h-3 w-3 animate-spin" /> : <Settings2 className="h-3 w-3" />}
                        Manage
                      </button>
                      {(tool.isConnected ?? connected[tool.name]) && <Check className="h-3.5 w-3.5 text-emerald-400" />}
                    </div>
                  )) : <p className="px-2 py-3 text-xs text-muted-foreground">No apps connected yet.</p>}
                </section>

                <section>
                  <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Connected agents</p>
                  {agentCards.length ? agentCards.map((agent) => (
                    <div key={agent.id} className="flex items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-white/5">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-primary/20 bg-primary/10"><Bot className="h-4 w-4 text-primary" /></div>
                      <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{agent.name}</p><p className="truncate text-xs text-muted-foreground">{agent.desc}</p></div>
                      <button type="button" onClick={() => openConnectionManager(agent.name)} disabled={connectionAction === agent.name} className="flex items-center gap-1 px-1.5 py-1 text-[10px] text-muted-foreground hover:text-foreground">
                        {connectionAction === agent.name ? <Loader2 className="h-3 w-3 animate-spin" /> : <Settings2 className="h-3 w-3" />}
                        Manage
                      </button>
                      <Check className="h-3.5 w-3.5 text-emerald-400" />
                    </div>
                  )) : <p className="px-2 py-3 text-xs text-muted-foreground">No agents connected yet.</p>}
                </section>

                <section>
                  <p className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Attached documents</p>
                  {documents.length ? documents.map((document) => (
                    <div key={`${document.name}:${document.file_url}`} className="flex items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-white/5">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/8 bg-secondary"><Paperclip className="h-4 w-4 text-primary" /></div>
                      <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{document.name}</p><p className="text-xs text-muted-foreground">Available to the next workflow</p></div>
                      <button type="button" aria-label={`Remove ${document.name}`} onClick={() => removeDocument(document.file_url, document.name)} className="p-1.5 text-muted-foreground hover:text-red-400"><Trash2 className="h-3.5 w-3.5" /></button>
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
                <button type="button" onClick={() => setTab("agents")} className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium ${tab === "agents" ? "border-primary text-primary" : "border-transparent text-muted-foreground"}`}><Bot className="h-3.5 w-3.5" />Agents</button>
              </div>

              {error && <p className="mx-5 mt-3 rounded-lg border border-red-400/20 bg-red-400/5 p-2 text-xs text-red-400">{error}</p>}
              {appPreset && <p role="status" className="mx-5 mt-3 rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs text-muted-foreground">{appPreset.message}</p>}

              {tab === "apps" ? (
                <>
                  <div className="px-5 py-4">
                    <h3 className="text-base font-semibold">App marketplace</h3>
                    <p className="mt-1 text-xs text-muted-foreground">Search apps and APIs across AURA’s embedded connector network. Provider credentials stay inside the secure connection flow.</p>
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
                      const isConnected = tool.isConnected ?? Boolean(connected[tool.name]);
                      return (
                        <div key={tool.rowKey || `${tool.provider}:${tool.name}`} data-connection-row={tool.rowKey} className="flex items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-white/5">
                          <div className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-lg border border-white/8 bg-secondary text-base">
                            {tool.logoUrl ? <img src={tool.logoUrl} alt="" className="h-6 w-6 object-contain" /> : tool.icon}
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium">{tool.displayName || tool.name}</p>
                            <p className="text-xs text-muted-foreground">{tool.desc}</p>
                          </div>
                          {tool.connectionId || isConnected ? (
                            <button type="button" onClick={() => openConnectionManager(tool)} className={`flex items-center gap-1 text-xs ${isConnected ? "text-emerald-400" : "text-amber-300"}`}>{isConnected && <Check className="h-3.5 w-3.5" />}Manage</button>
                          ) : tool.requestable && catalogSearchQuery !== query.trim().replace(/\s+/g, " ") ? (
                            searchingCatalog
                              ? <span className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Searching…</span>
                              : <span className="rounded-full border border-amber-400/20 bg-amber-400/5 px-2 py-1 text-[10px] text-amber-300">Coming soon</span>
                          ) : tool.requestable ? (
                            <button type="button" onClick={() => requestApp(tool)} disabled={requesting === tool.name} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50">
                              {requesting === tool.name ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}{requesting === tool.name ? "Requesting…" : "Request app"}
                            </button>
                          ) : tool.connectable ? (
                            <button type="button" onClick={() => connect(tool)} disabled={Boolean(connecting) || (isMetaConnection(tool) && !connectionsLoaded)} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/10 disabled:opacity-50">
                              {connecting === (tool.rowKey || tool.name) ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}{connecting === (tool.rowKey || tool.name) ? "Opening…" : "Connect"}
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
              ) : tab === "agents" ? (
                <div className="flex-1 overflow-y-auto p-5">
                  <AgentConnectionForm initialSource={preset?.source || ""} />
                </div>
              ) : (
                <div className="flex-1 overflow-y-auto p-5">
                  <h3 className="text-base font-semibold">Attach documents</h3>
                  <p className="mt-1 text-xs text-muted-foreground">Files uploaded here are available to the next workflow without leaving Connect.</p>
                  <div className="mt-4"><DocumentUpload documents={documents} onAttach={attachDocument} /></div>
                  <div className="mt-4 space-y-1">
                    {documents.map((document) => (
                      <div key={`${document.name}:${document.file_url}`} className="flex items-center gap-3 rounded-xl bg-white/5 p-2.5">
                        <Paperclip className="h-4 w-4 shrink-0 text-primary" />
                        <p className="min-w-0 flex-1 truncate text-sm">{document.name}</p>
                        <Check className="h-3.5 w-3.5 text-emerald-400" />
                        <button type="button" aria-label={`Remove ${document.name}`} onClick={() => removeDocument(document.file_url, document.name)} className="p-1 text-muted-foreground hover:text-red-400"><X className="h-3.5 w-3.5" /></button>
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
                <p className="text-sm font-semibold">{managedConnection.uiLabel || managedConnection.uiName || managedConnection.display_name}</p>
                <button type="button" aria-label="Close connection manager" onClick={() => setManagedConnection(null)} className="p-1.5 text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
              </div>
              <div className="px-6 py-6">
                <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${connectionIsReady(managedConnection) ? "border-emerald-400/15 bg-emerald-400/5" : "border-amber-400/20 bg-amber-400/5"}`}>
                  {connectionIsReady(managedConnection) && <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-400/15"><Check className="h-4 w-4 text-emerald-400" /></div>}
                  <div><p className={`text-xs font-medium ${connectionIsReady(managedConnection) ? "text-emerald-400" : "text-amber-300"}`}>{connectionIsReady(managedConnection) ? "Connected and verified" : managedConnection.enabled === false ? "Connection disabled" : "Connection needs checking"}</p><p className="mt-0.5 text-[11px] text-muted-foreground">AURA checks permissions for each plan before Start.</p></div>
                </div>
                {isMetaConnection(managedConnection) && <div className="mt-3 space-y-2 text-xs text-muted-foreground"><p>This connection has its own authorization. Testing, reconnecting or removing it leaves your other Meta Ads connections unchanged.</p><p>Connected means AURA can sign in and check the granted access. Before starting a report, compare its ad account ID with the account containing your campaigns in Ads Manager. A Meta login or business portfolio is a different account type.</p><p>If your ad account is missing, check that the Facebook login you use has access to it before reconnecting. A successful connection alone does not confirm campaign results.</p></div>}
                {managedConnection.identity?.domain && <p className="mt-2 text-sm">Verified store: <span className="font-medium">{managedConnection.identity.domain}</span></p>}
                {((managedConnection.slug === "google-ads" && managedConnection.connection_backend === "pipedream") ||
                  (managedConnection.slug === "reddit-ads" && managedConnection.connection_backend === "native")) && (
                  <div className="mt-4 rounded-xl border border-white/10 p-3">
                    <p className="text-sm font-medium">{(managedConnection.google_ads_account || managedConnection.reddit_ads_account)?.name || "Choose an advertising account"}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{(managedConnection.google_ads_account || managedConnection.reddit_ads_account)
                      ? "Selected for new workflows. Existing reviewed workflows keep their original account."
                      : "Sign-in is saved. Select an account to finish setup."}</p>
                    <button type="button" onClick={() => runConnectionAction(managedConnection.uiName, "account")} disabled={connectionAction === managedConnection.uiName} className="mt-3 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground disabled:opacity-40">
                      {(managedConnection.google_ads_account || managedConnection.reddit_ads_account) ? "Change ad account" : "Choose ad account"}
                    </button>
                  </div>
                )}
                {managedConnection.verification?.read_only && <p className="mt-2 text-xs text-muted-foreground">Read-only connection · {managedConnection.verification.pages_readable ? "Content page reads authorized" : "Content page scope not granted"}</p>}
                {managedConnection.is_agent && (
                  <div className="mt-4 rounded-xl border border-white/8 bg-white/5 p-3 text-[11px] text-muted-foreground">
                    <p><span className="text-foreground">Protocol:</span> {String(managedConnection.agent_protocol || "agent").toUpperCase()}</p>
                    <p className="mt-1"><span className="text-foreground">Owner:</span> {managedConnection.agent_owner || "Declared by provider"}</p>
                    <p className="mt-2 leading-relaxed">Artifact-only access. This agent cannot receive or invoke credentials for your connected apps.</p>
                  </div>
                )}
                {error && <p className="mt-4 rounded-lg border border-red-400/20 bg-red-400/5 p-2 text-xs text-red-400">{error}</p>}
              </div>
              <div className={`grid gap-2 border-t border-white/8 p-4 ${managedConnection.is_agent && !managedConnection.reconnect_supported ? "grid-cols-2" : "grid-cols-3"}`}>
                <button type="button" onClick={() => runConnectionAction(managedConnection.uiName, "test")} disabled={connectionAction === managedConnection.uiName} className="flex items-center justify-center gap-1.5 rounded-lg border border-white/10 px-2 py-2.5 text-xs font-medium hover:bg-white/5"><Check className="h-3.5 w-3.5" />Test</button>
                {(!managedConnection.is_agent || managedConnection.reconnect_supported) && <button type="button" onClick={() => runConnectionAction(managedConnection.uiName, "reconnect")} disabled={connectionAction === managedConnection.uiName} className="flex items-center justify-center gap-1.5 rounded-lg bg-primary px-2 py-2.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"><RefreshCw className="h-3.5 w-3.5" />Reconnect</button>}
                <button type="button" onClick={() => runConnectionAction(managedConnection.uiName, "disconnect")} disabled={connectionAction === managedConnection.uiName} className="flex items-center justify-center gap-1.5 rounded-lg border border-red-400/30 px-2 py-2.5 text-xs font-medium text-red-400 hover:bg-red-400/10"><Trash2 className="h-3.5 w-3.5" />Remove</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

