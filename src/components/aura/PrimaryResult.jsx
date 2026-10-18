/** @param {{ title: string, provider?: string, providerVerb?: string, actions?: import("react").ReactNode, footer?: import("react").ReactNode, children: import("react").ReactNode }} props */
export default function PrimaryResult({ title, provider, providerVerb = "Created in", actions, footer, children }) {
  return (
    <section aria-label="Main workflow result" className="mb-5 overflow-hidden rounded-3xl border border-primary/25 bg-gradient-to-br from-primary/[0.09] via-card/80 to-card/50 shadow-xl shadow-primary/[0.06]">
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 pb-4 pt-6 sm:px-7">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">Your result</p>
          <h2 className="text-xl font-semibold">{title}</h2>
          {provider && <p className="mt-1.5 text-xs text-muted-foreground">{providerVerb} {provider}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      <div className="px-5 pb-6 sm:px-7">{children}</div>
      {footer && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 px-5 py-3 text-xs sm:px-7">{footer}</div>}
    </section>
  );
}
