import { AlertTriangle, MessageSquare, Users, Mail, FileText, BarChart3, CheckCircle2, ExternalLink, Eye } from "lucide-react";

const TYPE_ICONS = {
  message: MessageSquare,
  crm: Users,
  email: Mail,
  document: FileText,
  metric: BarChart3,
  alert: AlertTriangle,
  approval: CheckCircle2,
};

export default function ProofLine({ outcome, onDetails }) {
  const Icon = outcome.attention ? AlertTriangle : TYPE_ICONS[outcome.type] || CheckCircle2;
  const count = outcome.count != null ? outcome.count : outcome.items?.length ?? null;
  const attention = !!outcome.attention;

  return (
    <div
      className={`flex items-center gap-3 p-3 rounded-xl border transition-colors ${
        attention ? "border-amber-400/30 bg-amber-400/[0.05]" : "border-white/6 bg-card/40 hover:bg-card/60"
      }`}
    >
      <div className={`p-1.5 rounded-lg flex-shrink-0 ${attention ? "bg-amber-400/10" : "bg-primary/10"}`}>
        <Icon className={`w-4 h-4 ${attention ? "text-amber-400" : "text-primary"}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          {count != null && <span className="text-lg font-bold leading-none">{count}</span>}
          <span className="text-sm">{outcome.title}</span>
        </div>
        {outcome.detail && (
          <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{outcome.detail}</p>
        )}
      </div>
      {outcome.link ? (
        <a
          href={outcome.link}
          target="_blank"
          rel="noopener noreferrer"
          className={`flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border flex-shrink-0 transition-colors ${
            attention
              ? "border-amber-400/30 text-amber-300 hover:bg-amber-400/10"
              : "border-accent/30 text-accent hover:bg-accent/10"
          }`}
        >
          {outcome.attention ? <Eye className="w-3 h-3" /> : <ExternalLink className="w-3 h-3" />}
          {outcome.linkLabel || "Open"}
        </a>
      ) : outcome.items && outcome.items.length > 0 ? (
        <button
          onClick={onDetails}
          className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full border border-primary/20 text-primary hover:bg-primary/10 transition-colors flex-shrink-0"
        >
          <Eye className="w-3 h-3" /> View details
        </button>
      ) : null}
    </div>
  );
}