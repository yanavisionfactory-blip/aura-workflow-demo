import { useState } from 'react';
import { ChevronDown, FileBarChart, X } from 'lucide-react';
import data from './data.mjs';

export function ResourceList() {
  return <div className="space-y-3">{data.sources.map((item) => <div key={item.key} className="rounded-xl border border-white/10 p-3"><div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">{item.name}</span><span className="text-[10px] uppercase text-violet-300">Simulated</span></div><p className="mt-1 text-xs leading-5 text-muted-foreground">{item.report}</p></div>)}<div className="rounded-xl border border-white/10 p-3"><p className="text-xs font-medium">Outside this scenario’s scope</p><p className="mt-2 text-xs leading-6 text-muted-foreground">{data.scope.excluded.join(' · ')} · Klaviyo SMS</p></div><p className="text-xs leading-6 text-muted-foreground">Prepared resources for a fictional client. No real SmartSites account data or live provider calls.</p></div>;
}
export default function DemoResources() {
  const [open, setOpen] = useState(false);
  return <div className="relative"><button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex items-center gap-2 rounded-full border border-white/10 bg-card/60 px-3 py-1.5 text-xs text-muted-foreground"><FileBarChart className="h-3.5 w-3.5 text-primary"/><span>3 sample sources</span><ChevronDown className="h-3 w-3"/></button>{open && <div className="absolute right-0 top-11 z-50 w-[min(23rem,88vw)] rounded-2xl border border-white/10 bg-[#101a2c] p-4 shadow-2xl"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Selected client scope</h2><button type="button" aria-label="Close resources" onClick={() => setOpen(false)}><X className="h-4 w-4"/></button></div><ResourceList/></div>}</div>;
}
