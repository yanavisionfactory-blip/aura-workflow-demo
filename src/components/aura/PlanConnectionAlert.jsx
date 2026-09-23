import { useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
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
  Plus,
  Loader2,
  CheckCircle2,
} from "lucide-react";

const TOOL_ICONS = {
  "Meta Ads": BarChart3,
  Gmail: Mail,
  HubSpot: Users,
  Salesforce: Users,
  Slack: MessageSquare,
  "Google Sheets": Table,
  "Google Docs": FileText,
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
  connectingTool,
  errors = {},
  onConnectAll,
  onRecheck,
  onSkipTool,
  onReplaceTool,
  replacements = [],
  userSelectedTools = [],
  connectionEnabled = true,
}) {
  const [replacing, setReplacing] = useState("");
  const [replacement, setReplacement] = useState("");
  // Only surface connect prompts for tools AURA chose on its own (the user did
  // not pin them in the command input) and that aren't connected. Tools the
  // user explicitly selected are their responsibility — they connect those in
  // the command input, so we don't nag about them here.
  const checklist = tools.filter((t) => !userSelectedTools.includes(t.name));
  const needed = checklist.filter((t) => !connections[t.name]);
  if (needed.length === 0) return null;
  const connectedCount = checklist.length - needed.length;

  const isConnecting = Boolean(connectingTool);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-4 rounded-xl border border-white/8 bg-card/60 overflow-hidden"
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/6">
        <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-semibold">AURA connection checklist</p>
          <p className="text-[11px] text-muted-foreground">
            {connectedCount} of {checklist.length} required {checklist.length === 1 ? "account" : "accounts"} connected
          </p>
        </div>
      </div>

      {/* Primary action — at the top so it's immediately reachable */}
      <div className="p-3 border-b border-white/6">
        <button
          onClick={onConnectAll}
          disabled={isConnecting || !connectionEnabled}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:cursor-wait disabled:opacity-70"
        >
          {isConnecting || !connectionEnabled
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <Plus className="w-3.5 h-3.5" />}
          {isConnecting
            ? `Connecting ${connectingTool}…`
            : connectionEnabled
              ? needed.length === 1 ? `Connect ${needed[0].name}` : "Connect remaining accounts"
              : "Validating required accounts…"}
        </button>
      </div>

      <div className="divide-y divide-white/5">
        {checklist.map((t) => {
          const Icon = iconFor(t.name);
          const error = errors[t.name];
          const connected = Boolean(connections[t.name]);
          return (
            <div key={t.name} className="flex items-start gap-3 px-4 py-3">
              <div className="mt-0.5 p-1.5 rounded-lg bg-secondary/60 border border-white/8 flex-shrink-0">
                <Icon className="w-3.5 h-3.5 text-foreground/70" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{t.name}</span>
                  <span className={`inline-flex items-center gap-1 text-[11px] ${connected ? "text-emerald-400" : "text-amber-400"}`}>
                    {connected && <CheckCircle2 className="h-3 w-3" />}
                    {connected ? "Connected" : "Connection needed"}
                  </span>
                </div>
                {t.reason && (
                  <p className="text-[11px] text-muted-foreground/70 mt-0.5 leading-relaxed">{cap(t.reason)}.</p>
                )}
                {error && <p className="mt-1 text-[11px] leading-relaxed text-red-300">{error}</p>}
                {!connected && connectionEnabled && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <button type="button" onClick={() => onRecheck?.(t.name)} disabled={isConnecting}
                      className="rounded-md border border-white/15 px-2.5 py-1 text-[11px] text-foreground hover:bg-white/5 disabled:opacity-50">
                      I've connected it — check again
                    </button>
                    {onSkipTool && <button type="button" onClick={() => onSkipTool(t.name)} disabled={isConnecting}
                      className="rounded-md border border-white/15 px-2.5 py-1 text-[11px] text-foreground hover:bg-white/5 disabled:opacity-50">
                      Run without {t.name}
                    </button>}
                    {onReplaceTool && replacements.length > 0 && <button type="button"
                      onClick={() => { setReplacing(replacing === t.name ? "" : t.name); setReplacement(""); }}
                      disabled={isConnecting} className="rounded-md border border-white/15 px-2.5 py-1 text-[11px] text-foreground hover:bg-white/5 disabled:opacity-50">
                      Replace tool
                    </button>}
                    {replacing === t.name && <div className="flex items-center gap-2 w-full">
                      <select aria-label={`Replacement for ${t.name}`} value={replacement}
                        onChange={(event) => setReplacement(event.target.value)}
                        className="rounded-md border border-white/15 bg-card px-2 py-1 text-xs">
                        <option value="">Choose a connected app</option>
                        {replacements.filter((name) => name !== t.name).map((name) => (
                          <option key={name} value={name}>{name}</option>
                        ))}
                      </select>
                      <button type="button" disabled={!replacement} onClick={() => onReplaceTool(t.name, replacement)}
                        className="rounded-md bg-primary px-2.5 py-1 text-xs text-primary-foreground disabled:opacity-50">
                        Revise plan
                      </button>
                    </div>}
                    <p className="w-full text-[11px] text-muted-foreground/70">AURA will build a new plan for your review before any external action.</p>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

    </motion.div>
  );
}
