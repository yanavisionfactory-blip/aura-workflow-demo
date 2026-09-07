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
  connectingTool,
  errors = {},
  onConnectAll,
  userSelectedTools = [],
}) {
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

  const isConnecting = Boolean(connectingTool);

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
          disabled={isConnecting}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:cursor-wait disabled:opacity-70"
        >
          {isConnecting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
          {isConnecting ? `Connecting ${connectingTool}…` : "Connect & continue"}
        </button>
      </div>

      <div className="divide-y divide-white/5">
        {needed.map((t) => {
          const Icon = iconFor(t.name);
          const error = errors[t.name];
          return (
            <div key={t.name} className="flex items-start gap-3 px-4 py-3">
              <div className="mt-0.5 p-1.5 rounded-lg bg-secondary/60 border border-white/8 flex-shrink-0">
                <Icon className="w-3.5 h-3.5 text-foreground/70" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{t.name}</span>
                  <span className="text-[11px] text-amber-400">Connection needed</span>
                </div>
                {t.reason && (
                  <p className="text-[11px] text-muted-foreground/70 mt-0.5 leading-relaxed">{cap(t.reason)}.</p>
                )}
                {error && <p className="mt-1 text-[11px] leading-relaxed text-red-300">{error}</p>}
              </div>
            </div>
          );
        })}
      </div>

    </motion.div>
  );
}
