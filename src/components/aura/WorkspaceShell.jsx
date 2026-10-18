import TopBar from "./TopBar";
import AmbientBackground from "./AmbientBackground";

export default function WorkspaceShell({ phase = "results", onHistoryOpen, onBack, backLabel, children }) {
  return (
    <div className="relative min-h-screen bg-background font-inter">
      <AmbientBackground phase={phase} />
      <div className="relative z-10 flex min-h-screen flex-col">
        <TopBar onHistoryOpen={onHistoryOpen} onBack={onBack} backLabel={backLabel} />
        {children}
        <footer className="flex items-center justify-between border-t border-white/5 px-6 py-3">
          <span className="text-[11px] text-muted-foreground/40">AURA · Connected workflows</span>
          <div className="flex items-center gap-1">
            <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
            <span className="text-[11px] text-muted-foreground/40">System ready</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
