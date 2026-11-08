import { useState } from "react";
import { ArrowUpRight, MonitorUp } from "lucide-react";

export default function NativeToolView({ tool, model }) {
  const [embedFailed, setEmbedFailed] = useState(false);
  const embedded = Boolean(model.embedUrl && !embedFailed);
  return <section aria-label={`${tool} native view`} className="overflow-hidden rounded-xl border border-white/10 bg-[#080f1b]">
    {embedded && <iframe title={`${tool} native design viewer`} src={model.embedUrl} loading="lazy" referrerPolicy="no-referrer" allowFullScreen className="aspect-video min-h-72 w-full border-0 bg-white" onError={() => setEmbedFailed(true)} />}
    <div className="space-y-4 p-5 sm:p-6">
      <div className="flex items-start gap-3"><MonitorUp className="mt-1 h-6 w-6 shrink-0 text-cyan-300" /><div className="min-w-0"><h4 className="text-base font-semibold">{embedded ? "Canva design viewer" : model.title}</h4><p className="mt-1 break-words text-sm text-slate-300">{model.detail}</p></div><span className="ml-auto shrink-0 rounded-full border border-white/10 px-2.5 py-1 text-[10px] text-slate-400">{embedded ? "Embedded" : "New tab"}</span></div>
      {model.accounts?.length > 0 && <div><p className="mb-2 text-xs text-slate-400">{tool === "Google Ads" ? "Customer account used" : "Ad account used"}</p><div className="flex flex-wrap gap-2">{model.accounts.map((id) => <span key={id} className="rounded-lg bg-white/5 px-3 py-2 text-sm font-medium tabular-nums text-slate-100">{tool === "Google Ads" ? id.replace(/^(\d{3})(\d{3})(\d{4})$/, "$1-$2-$3") : id}</span>)}</div></div>}
      <p className="max-w-2xl text-sm leading-6 text-slate-400">{model.note}</p>
      <div className="flex flex-wrap gap-3">{model.targets.map((target) => <a key={target.link} href={target.link} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-violet-500 px-5 py-3 text-sm font-semibold text-white hover:bg-violet-400 sm:w-auto">{target.label}<ArrowUpRight className="h-4 w-4" /></a>)}</div>
      {!embedded && <p className="max-w-2xl text-xs leading-5 text-slate-400">{model.help} These links use your browser’s sign-in, which may differ from your AURA connection.</p>}
    </div>
  </section>;
}
