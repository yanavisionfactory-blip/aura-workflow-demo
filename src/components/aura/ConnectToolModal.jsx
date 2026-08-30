import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Loader2, Plus, ScanSearch, X, ShieldCheck, KeyRound } from "lucide-react";

// Popup that appears when a user selects (pins) a tool that isn't connected yet.
// The user picked the tool first; now AURA asks them to authorize access to it
// as a separate, explicit step. Connecting happens here — behind the scenes
// AURA decides the method (oauth / mcp / interface) via connectTool.
//
// Also supports a "custom integration" category: a tool the user uses at work
// that isn't in AURA's common list. In custom mode the user types the tool name
// (and optionally what it does) and AURA learns its interface to connect it.

export default function ConnectToolModal({ tool, onConnect, onClose, connecting }) {
  const isInterface = tool?.interface;
  const isApiKey = tool?.apiKey;
  const startCustom = tool?.custom || !tool?.name;
  const [customMode, setCustomMode] = useState(startCustom);
  const [name, setName] = useState(tool?.name || "");
  const [desc, setDesc] = useState(tool?.desc || "");
  const [apiKey, setApiKey] = useState("");
  const [connectionKind, setConnectionKind] = useState("openapi");
  const [baseUrl, setBaseUrl] = useState("");
  const [credentialHeader, setCredentialHeader] = useState("Authorization");
  const [authorizationUrl, setAuthorizationUrl] = useState("");
  const [tokenUrl, setTokenUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [scopes, setScopes] = useState("");

  // Re-sync fields when a new tool is presented (the modal instance persists
  // across triggers, so useState only initializes once).
  useEffect(() => {
    if (!tool) return;
    setCustomMode(tool.custom || !tool.name);
    setName(tool.name || "");
    setDesc(tool.desc || "");
    setApiKey("");
    setConnectionKind("openapi");
    setBaseUrl("");
    setCredentialHeader("Authorization");
    setAuthorizationUrl("");
    setTokenUrl("");
    setClientId("");
    setClientSecret("");
    setScopes("");
  }, [tool]);

  const canConnect = customMode
    ? name.trim().length > 0 && /^https:\/\//i.test(baseUrl.trim())
      && (connectionKind !== "api_key" || apiKey.trim().length > 0)
      && (connectionKind !== "oauth2" || (
        /^https:\/\//i.test(authorizationUrl.trim())
        && /^https:\/\//i.test(tokenUrl.trim())
        && clientId.trim().length > 1
      ))
    : isApiKey ? apiKey.trim().length > 0 : !!tool?.name;

  const handleConnect = () => {
    if (!canConnect) return;
    if (customMode) {
      onConnect({
        name: name.trim(),
        desc: desc.trim(),
        custom: true,
        connectionKind,
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim(),
        credentials: apiKey.trim() ? { api_key: apiKey.trim(), header: credentialHeader.trim() || "Authorization", prefix: credentialHeader === "Authorization" ? "Bearer" : "" } : {},
        authorizationUrl: authorizationUrl.trim(),
        tokenUrl: tokenUrl.trim(),
        clientId: clientId.trim(),
        clientSecret: clientSecret.trim(),
        scopes: scopes.split(/[\s,]+/).map((scope) => scope.trim()).filter(Boolean),
      });
    } else if (isApiKey) {
      onConnect({ ...tool, apiKey: apiKey.trim() });
    } else {
      onConnect(tool);
    }
  };

  return (
    <AnimatePresence>
      {tool && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ duration: 0.18 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-2xl border border-white/10 bg-card shadow-2xl overflow-hidden"
          >
            <div className="flex items-center justify-between px-4 pt-4 pb-2">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
                  {customMode ? (
                    <Plus className="w-4 h-4 text-primary" />
                  ) : isApiKey ? (
                    <KeyRound className="w-4 h-4 text-primary" />
                  ) : isInterface ? (
                    <ScanSearch className="w-4 h-4 text-primary" />
                  ) : (
                    <Plus className="w-4 h-4 text-primary" />
                  )}
                </div>
                <h3 className="text-sm font-semibold">
                  {customMode ? "Custom integration" : `Connect ${tool.name}`}
                </h3>
              </div>
              <button onClick={onClose} className="p-1 rounded-lg text-muted-foreground hover:text-foreground hover:bg-white/5">
                <X className="w-4 h-4" />
              </button>
            </div>

            {customMode ? (
              <div className="px-4 pb-2 space-y-2">
                <p className="text-xs text-muted-foreground leading-relaxed">
                  Connect any API, MCP server, agent, plugin, webhook, or web application. AURA verifies the endpoint before enabling it.
                </p>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                  placeholder="Tool name (e.g. Internal CRM)"
                  className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40"
                />
                <input
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  placeholder="What does it do? (optional)"
                  className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40"
                />
                <select value={connectionKind} onChange={(e) => setConnectionKind(e.target.value)} className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40">
                  <option value="openapi">REST / OpenAPI API</option>
                  <option value="oauth2">OAuth 2.0 / OpenID Connect</option>
                  <option value="api_key">API-key service</option>
                  <option value="mcp">MCP server</option>
                  <option value="agent">External agent</option>
                  <option value="plugin">Plugin manifest</option>
                  <option value="webhook">Webhook</option>
                  <option value="browser">Web app / browser connector</option>
                </select>
                <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={connectionKind === "mcp" ? "https://tool.example.com/mcp" : "https://api.example.com"} className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono" />
                {connectionKind === "oauth2" && (
                  <>
                    <input value={authorizationUrl} onChange={(e) => setAuthorizationUrl(e.target.value)} placeholder="Authorization URL" className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono" />
                    <input value={tokenUrl} onChange={(e) => setTokenUrl(e.target.value)} placeholder="Token URL" className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono" />
                    <input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="OAuth client ID" className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono" />
                    <input value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} type="password" placeholder="OAuth client secret (optional for public clients)" className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono" />
                    <input value={scopes} onChange={(e) => setScopes(e.target.value)} placeholder="Scopes, separated by spaces or commas" className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono" />
                    <p className="text-[10px] text-amber-300/80">Register this callback with the provider: https://impartial-emotion-production-49d4.up.railway.app/v1/oauth/custom/callback</p>
                  </>
                )}
                {!["mcp", "webhook", "browser", "oauth2"].includes(connectionKind) && (
                  <>
                    <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} type="password" placeholder={connectionKind === "api_key" ? "API key (required)" : "API key or bearer token (optional)"} className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono" />
                    {apiKey && <input value={credentialHeader} onChange={(e) => setCredentialHeader(e.target.value)} placeholder="Header name" className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono" />}
                  </>
                )}
                <p className="text-[10px] text-muted-foreground/60">AURA discovers capabilities, tests the endpoint, and encrypts credentials. The connection is shown only after verification succeeds.</p>
              </div>
            ) : isApiKey ? (
              <div className="px-4 pb-2 space-y-2">
                <p className="text-xs text-muted-foreground leading-relaxed">
                  <span className="text-foreground font-medium">{tool.name}</span> needs an API key to return verified
                  data. Paste your key — AURA stores it securely and uses it to call {tool.name} on your behalf.
                </p>
                <p className="text-[11px] text-muted-foreground/60 leading-relaxed">{tool.desc}</p>
                <input
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  autoFocus
                  type="password"
                  placeholder="Paste your API key"
                  className="w-full bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40 font-mono"
                />
                <p className="text-[10px] text-muted-foreground/50 leading-relaxed">
                  Get a key from {tool.name}'s dashboard. Without it, AURA falls back to unverified web-search results.
                </p>
              </div>
            ) : (
              <div className="px-4 pb-2">
                <p className="text-xs text-muted-foreground leading-relaxed">
                  You selected <span className="text-foreground font-medium">{tool.name}</span>. AURA needs access to run
                  actions with it on your behalf.
                </p>
                <p className="text-[11px] text-muted-foreground/60 mt-2 leading-relaxed">{tool.desc}</p>
                <button
                  onClick={() => {
                    setCustomMode(true);
                    setName("");
                    setDesc("");
                  }}
                  className="mt-2 flex items-center gap-1 text-[11px] text-primary/80 hover:text-primary transition-colors"
                >
                  <Plus className="w-3 h-3" /> Add a custom tool instead
                </button>
              </div>
            )}

            <div className="px-4 py-2 flex items-center gap-1.5 text-[10px] text-muted-foreground/70 bg-secondary/40 border-y border-white/5">
              <ShieldCheck className="w-3 h-3 text-emerald-400/80" />
              You can revoke access anytime from your workspace.
            </div>

            <div className="flex items-center gap-2 p-4">
              <button
                onClick={onClose}
                className="flex-1 text-xs px-3 py-2 rounded-lg border border-white/10 text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
              >
                Not now
              </button>
              <button
                onClick={handleConnect}
                disabled={connecting || !canConnect}
                className="flex-1 flex items-center justify-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {connecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                {connecting ? "Connecting…" : "Connect"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
