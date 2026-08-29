import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  Check,
  BarChart3,
  Mail,
  Users,
  MessageSquare,
  Table,
  Calendar,
  FileText,
  CheckSquare,
  CreditCard,
  Sparkles,
  Box,
  ScanSearch,
  Plus,
  X,
  Loader2,
} from "lucide-react";

const TOOL_ICONS = {
  "Meta Ads": BarChart3,
  Gmail: Mail,
  HubSpot: Users,
  Salesforce: Users,
  Slack: MessageSquare,
  "Google Sheets": Table,
  "Google Calendar": Calendar,
  Notion: FileText,
  Jira: CheckSquare,
  Stripe: CreditCard,
  "AURA Intelligence": Sparkles,
};

const iconFor = (name) => TOOL_ICONS[name] || Box;

// Capitalize the first letter of a lowercase "iWill" sentence for the subtext.
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");

export default function PlanConnectionAlert({
  tools,
  connections,
  interfaceTools = {},
  connectingTool,
  authRequired = {},
  onConnect,
  onConnectAll,
  onConnectCustom,
  userSelectedTools = [],
}) {
  const [customOpen, setCustomOpen] = useState(false);
  const [customName, setCustomName] = useState("");

  // Only surface connect prompts for tools AURA chose on its own (the user did
  // not pin them in the command input) and that aren't connected. Tools the
  // user explicitly selected are their responsibility — they connect those in
  // the command input, so we don't nag about them here.
  const needed = tools.filter((t) => !connections[t.name] && !userSelectedTools.includes(t.name));
  if (needed.length === 0) return null;
  const count = needed.length;
  const headerLabel =
    count === 1
      ? `Connect ${needed[0].name} to continue`
      : count === 2
      ? `Connect ${needed[0].name} and ${needed[1].name} to continue`
      : `Connect ${count} tools to continue`;

  const submitCustom = () => {
    const name = customName.trim();
    if (!name) return;
    onConnectCustom(name);
    setCustomOpen(false);
    setCustomName("");
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-4 rounded-xl border border-white/8 bg-card/60 overflow-hidden"
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/6">
        <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
        <span className="text-sm font-semibold">{headerLabel}</span>
      </div>

      {/* Primary action — at the top so it's immediately reachable */}
      <div className="p-3 border-b border-white/6">
        <button
          onClick={onConnectAll}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" /> Connect &amp; continue
        </button>
      </div>

      <div className="divide-y divide-white/5">
        {needed.map((t) => {
          const Icon = iconFor(t.name);
          const connected = connections[t.name];
          const isInterface = !!interfaceTools[t.name];
          const isAuthRequired = authRequired[t.name];
          const isConnecting = connectingTool === t.name;
          return (
            <div key={t.name} className="flex items-start gap-3 px-4 py-3">
              <div className="mt-0.5 p-1.5 rounded-lg bg-secondary/60 border border-white/8 flex-shrink-0">
                <Icon className="w-3.5 h-3.5 text-foreground/70" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{t.name}</span>
                  {connected ? (
                    <span className="flex items-center gap-1 text-[11px] text-emerald-400">
                      <Check className="w-3 h-3" /> Connected
                    </span>
                  ) : isAuthRequired ? (
                    <span className="flex items-center gap-1 text-[11px] text-amber-400">
                      <AlertTriangle className="w-3 h-3" /> Authorization required
                    </span>
                  ) : isConnecting ? (
                    <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Loader2 className="w-3 h-3 animate-spin" /> Connecting…
                    </span>
                  ) : (
                    <button
                      onClick={() => onConnect(t.name)}
                      className="flex items-center gap-1 text-[11px] text-amber-400 hover:text-amber-300 transition-colors"
                    >
                      {isInterface ? (
                        <>
                          <ScanSearch className="w-3 h-3" /> Connect tool
                        </>
                      ) : (
                        <>
                          <Plus className="w-3 h-3" /> Connect
                        </>
                      )}
                    </button>
                  )}
                </div>
                {isAuthRequired ? (
                  <p className="text-[11px] text-amber-400/70 mt-0.5 leading-relaxed">
                    OAuth access needed — ask AURA to authorize {t.name}, then it can run for real.
                  </p>
                ) : isInterface && !connected ? (
                  <p className="text-[11px] text-muted-foreground/70 mt-0.5 leading-relaxed">
                    No standard connection available. AURA can learn to work with the tool you already use.
                  </p>
                ) : (
                  t.reason && (
                    <p className="text-[11px] text-muted-foreground/70 mt-0.5 leading-relaxed">{cap(t.reason)}.</p>
                  )
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Connect a custom integration (no standard OAuth — AURA learns the interface) */}
      <div className="p-3 border-t border-white/6">
        <AnimatePresence mode="wait">
          {!customOpen ? (
            <motion.button
              key="open"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setCustomOpen(true)}
              className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-dashed border-white/10 text-xs text-muted-foreground hover:text-foreground hover:border-primary/30 transition-all"
            >
              <Plus className="w-3.5 h-3.5" /> Connect a custom integration
            </motion.button>
          ) : (
            <motion.div
              key="form"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-2"
            >
              <div className="flex items-center gap-2">
                <input
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      submitCustom();
                    }
                  }}
                  autoFocus
                  placeholder="Tool name (e.g. Internal CRM)"
                  className="flex-1 bg-card/70 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40 placeholder:text-muted-foreground/40"
                />
                <button
                  onClick={submitCustom}
                  disabled={!customName.trim()}
                  className="px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  Connect
                </button>
                <button
                  onClick={() => {
                    setCustomOpen(false);
                    setCustomName("");
                  }}
                  className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-white/5 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground/60 leading-relaxed">
                AURA will learn the tool's web interface — no API needed. You approve every action before it runs.
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}