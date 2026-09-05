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
  authRequired = {},
  onConnect,
  onConnectAll,
}) {
  const needed = tools.filter((t) => !connections[t.name]);
  if (needed.length === 0) return null;
  const count = needed.length;
  const headerLabel = `${count} connection${count === 1 ? "" : "s"} needed`;

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

      <div className="divide-y divide-white/5">
        {needed.map((t) => {
          const Icon = iconFor(t.name);
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
                  {isAuthRequired ? (
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
                      <Plus className="w-3 h-3" /> Connect
                    </button>
                  )}
                </div>
                {isAuthRequired ? (
                  <p className="text-[11px] text-amber-400/70 mt-0.5 leading-relaxed">
                    OAuth access needed — ask AURA to authorize {t.name}, then it can run for real.
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
      <div className="p-3 border-t border-white/6">
        <button
          onClick={onConnectAll}
          disabled={Boolean(connectingTool)}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {connectingTool ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
          Connect required {count === 1 ? "app" : "apps"}
        </button>
      </div>
    </motion.div>
  );
}
