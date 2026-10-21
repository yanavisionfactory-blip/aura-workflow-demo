import { useState } from 'react';
import { FlaskConical, FileText } from 'lucide-react';

export default function WebsiteCMSPreview({ output }) {
  const [selected, setSelected] = useState(output.pages[0].page_id);
  const page = output.pages.find((item) => item.page_id === selected) || output.pages[0];
  return <section aria-label={`${output.name} simulated output`} className="space-y-5">
    <header className="rounded-xl border border-violet-300/25 bg-violet-300/5 p-5">
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-violet-300"><FlaskConical className="h-4 w-4"/>Simulated tool output</p>
      <h3 className="mt-3 text-xl font-semibold">{output.name}</h3>
      <p className="mt-2 text-sm text-slate-200">{output.summary}</p>
      <p className="mt-2 text-xs leading-6 text-muted-foreground">{output.detail}</p>
      <p className="mt-3 border-t border-white/10 pt-3 text-xs leading-6 text-violet-200">Preview generated in AURA · 0 external calls · 0 CMS records created · Content approval pending</p>
    </header>
    <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr>{['Page', 'Proposed route', 'Content version', 'Remote record', 'State'].map((label) => <th key={label} className="p-3">{label}</th>)}</tr></thead><tbody>{output.pages.map((item) => <tr key={item.page_id} className="border-t border-white/10"><th className="p-3"><button type="button" aria-pressed={page.page_id === item.page_id} onClick={() => setSelected(item.page_id)} className="text-primary underline underline-offset-4">Inspect {item.page_id}</button></th><td className="p-3 font-mono">{item.proposed_path}</td><td className="p-3 font-mono">{item.content_version}</td><td className="p-3 text-muted-foreground">Not created</td><td className="p-3 text-violet-200">Simulated · unpublished</td></tr>)}</tbody></table></div>
    <article aria-label={`${output.name} ${page.page_id} draft payload`} className="rounded-xl border border-white/10 p-5">
      <p className="flex items-center gap-2 text-xs text-primary"><FileText className="h-4 w-4"/>{page.page_id} · {page.content_version}</p>
      <h4 className="mt-3 text-lg font-semibold">{page.title}</h4>
      <p className="mt-3 text-sm leading-7 text-slate-300">{page.purpose}</p>
      <dl className="mt-5 grid gap-4 text-xs sm:grid-cols-2"><div><dt className="text-muted-foreground">Page title</dt><dd className="mt-1 leading-6">{page.seo.page_title}</dd></div><div><dt className="text-muted-foreground">Meta description</dt><dd className="mt-1 leading-6">{page.seo.meta_description}</dd></div><div><dt className="text-muted-foreground">Call to action</dt><dd className="mt-1 leading-6">{page.cta.label}<span className="block break-all text-muted-foreground">{page.cta.target}</span></dd></div><div><dt className="text-muted-foreground">Assets</dt><dd className="mt-1 leading-6">{page.asset_requirements.length} requirements · rights review pending</dd></div></dl>
      <details open className="mt-5 border-t border-white/10 pt-4"><summary className="cursor-pointer text-xs font-semibold">Complete HTML body · {page.page_id}</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/20 p-4 text-xs leading-6 text-slate-300">{page.body_html}</pre></details>
    </article>
    <details className="rounded-xl border border-white/10 p-4"><summary className="cursor-pointer text-xs font-semibold">Structured {output.name} output · all five pages</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs leading-6">{JSON.stringify(output, null, 2)}</pre></details>
  </section>;
}
