import { useState } from 'react';
import { ChevronDown, FileSearch, X } from 'lucide-react';

export const resources = [
  ['Screaming Frog', 'Real export', '171 URL records · original rows retained · client anonymized'],
  ['Semrush', 'Simulated', 'Keyword, ranking and competitor examples'],
  ['Ahrefs', 'Simulated', 'Visibility and fictional backlink examples'],
  ['Sitebulb', 'Simulated', 'Derived crawl checks and hypothetical audit hints'],
];

export function ResourceList() {
  return <div className="space-y-3">{resources.map(([name, status, detail]) => <div key={name} className="rounded-xl border border-white/10 p-3"><div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">{name}</span><span className={`text-[10px] uppercase ${status === 'Real export' ? 'text-emerald-300' : 'text-violet-300'}`}>{status}</span></div><p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p></div>)}<p className="text-xs leading-5 text-muted-foreground">These are prepared demo resources. This page does not connect accounts or call providers.</p></div>;
}

export default function DemoResources() {
  const [open, setOpen] = useState(false);
  return <div className="relative"><button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex items-center gap-2 rounded-full border border-white/10 bg-card/60 px-3 py-1.5 text-xs text-muted-foreground"><FileSearch className="h-3.5 w-3.5 text-primary"/><span className="hidden sm:inline">4 demo resources</span><span className="sm:hidden">Resources</span><ChevronDown className="h-3 w-3"/></button>{open && <div className="absolute right-0 top-11 z-50 w-[min(22rem,88vw)] rounded-2xl border border-white/10 bg-[#101a2c] p-4 shadow-2xl"><div className="mb-3 flex items-center justify-between"><h2 className="text-sm font-semibold">Workflow resources</h2><button type="button" aria-label="Close resources" onClick={() => setOpen(false)}><X className="h-4 w-4"/></button></div><ResourceList/></div>}</div>;
}
