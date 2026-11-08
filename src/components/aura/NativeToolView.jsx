import { ArrowUpRight } from "lucide-react";

export default function NativeToolView({ tool, model, isPrimary = false }) {
  return <nav aria-label={`${tool} native links`} className="flex flex-wrap gap-2">
    {model.targets.map((target) => <a key={target.link} href={target.link} target="_blank" rel="noopener noreferrer"
      title={`${model.note} Uses your browser’s sign-in.`}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold ${isPrimary ? "bg-violet-500 text-white hover:bg-violet-400" : "border border-white/15 text-cyan-200 hover:bg-white/5"}`}>
      {target.label}<ArrowUpRight className="h-4 w-4" />
    </a>)}
  </nav>;
}
