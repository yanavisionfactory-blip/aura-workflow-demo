import { CheckCircle2, AlertCircle, Loader2, Clock, ChevronRight, CalendarClock, Layers } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

const statusConfig = {
  completed: { icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-400/10", label: "Completed" },
  running:   { icon: Loader2,      color: "text-accent",       bg: "bg-accent/10",       label: "Running", spin: true },
  failed:    { icon: AlertCircle,  color: "text-red-400",      bg: "bg-red-400/10",      label: "Needs attention" },
};

export default function WorkflowList({ workflows, scheduledPrompts, onSelect }) {
  if (workflows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-center px-6">
        <div className="w-10 h-10 rounded-xl bg-muted/30 flex items-center justify-center mb-3">
          <Layers className="w-5 h-5 text-muted-foreground/40" />
        </div>
        <p className="text-sm text-muted-foreground">No saved workflows yet</p>
        <p className="text-xs text-muted-foreground/50 mt-1">Workflows you run are saved here to run again</p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-1.5">
      {workflows.map((wf) => {
        const cfg = statusConfig[wf.last_run_status] || statusConfig.completed;
        const Icon = cfg.icon;
        const scheduled = scheduledPrompts.has(wf.prompt);
        return (
          <button
            key={wf.id}
            onClick={() => onSelect(wf)}
            className="w-full text-left p-3.5 rounded-xl border border-white/5 bg-card/40 hover:bg-card/80 hover:border-white/10 transition-all group"
          >
            <div className="flex items-start gap-3">
              <div className={`flex-shrink-0 w-8 h-8 rounded-lg ${cfg.bg} flex items-center justify-center mt-0.5`}>
                <Icon className={`w-4 h-4 ${cfg.color} ${cfg.spin ? "animate-spin" : ""}`} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium leading-snug truncate">{wf.name || wf.prompt?.slice(0, 60)}</p>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <span className={`text-[11px] font-medium ${cfg.color}`}>{cfg.label}</span>
                  <span className="text-[11px] text-muted-foreground/40">·</span>
                  <span className="text-[11px] text-muted-foreground/50 flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {wf.last_run_date ? formatDistanceToNow(new Date(wf.last_run_date), { addSuffix: true }) : "Not run yet"}
                  </span>
                  {wf.run_count > 1 && (
                    <>
                      <span className="text-[11px] text-muted-foreground/40">·</span>
                      <span className="text-[11px] text-muted-foreground/50">{wf.run_count} runs</span>
                    </>
                  )}
                  {scheduled && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-primary/15 text-primary flex items-center gap-1">
                      <CalendarClock className="w-2.5 h-2.5" /> Scheduled
                    </span>
                  )}
                </div>
              </div>
              <ChevronRight className="w-4 h-4 text-muted-foreground/30 group-hover:text-muted-foreground transition-colors flex-shrink-0 mt-1" />
            </div>
          </button>
        );
      })}
    </div>
  );
}