import { AlertTriangle, CheckCircle2 } from "lucide-react";

/** @param {{ title: import("react").ReactNode, summary?: import("react").ReactNode, isFailure?: boolean, eyebrow?: import("react").ReactNode, heading?: "h1" | "h2", centered?: boolean, children?: import("react").ReactNode }} props */
export function ResultsHeading({ title, summary, isFailure = false, eyebrow, heading: Heading = "h2", centered = false, children }) {
  return (
    <div className={`mb-7 flex gap-4 ${centered ? "flex-col items-center text-center" : "items-start"}`}>
      <div className={`shrink-0 rounded-2xl border p-3 ${isFailure ? "border-amber-400/20 bg-amber-400/10" : "border-emerald-400/20 bg-emerald-400/10"}`}>
        {isFailure ? <AlertTriangle className="h-7 w-7 text-amber-400" /> : <CheckCircle2 className="h-7 w-7 text-emerald-400" />}
      </div>
      <div className="min-w-0 flex-1">
        {eyebrow && <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">{eyebrow}</p>}
        <Heading className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</Heading>
        {summary && <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">{summary}</p>}
        {children}
      </div>
    </div>
  );
}

export function ResultsMetrics({ metrics }) {
  if (!metrics.length) return null;
  return (
    <div className="mb-7 grid gap-3 sm:grid-cols-3">
      {metrics.map((metric, index) => <div key={`${metric.label}:${index}`} className="rounded-2xl border border-white/10 bg-card/60 px-5 py-4">
        <p className="text-3xl font-semibold tracking-tight text-foreground">{metric.value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{metric.label}</p>
      </div>)}
    </div>
  );
}
