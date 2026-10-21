import { useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { websitePageName, websiteToolOutcome } from '@/lib/websiteToolOutcomes.mjs';

export default function WebsiteCMSPreview({ output }) {
  const [selected, setSelected] = useState(output.pages[0].page_id);
  const page = output.pages.find(item => item.page_id === selected) || output.pages[0];
  const outcome = websiteToolOutcome(output.name);
  return <section aria-label={`${output.name} simulated outcome`} className="space-y-5 rounded-2xl border border-white/10 p-5">
    <header><p className="flex items-center gap-2 text-xs text-violet-300"><FlaskConical className="h-4 w-4"/>Simulated {output.name} outcome</p><h3 className="mt-3 text-xl font-semibold">{outcome.part}</h3><p className="mt-3 text-sm leading-7 text-slate-300">{outcome.result}</p></header>
    <nav aria-label={`${output.name} pages`} className="flex flex-wrap gap-2">{output.pages.map(item => <button type="button" key={item.page_id} aria-pressed={page.page_id === item.page_id} onClick={() => setSelected(item.page_id)} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-primary">{websitePageName(item.source_live_url)}</button>)}</nav>
    <article className="rounded-xl bg-[#f6f5f0] p-5 text-[#172536] sm:p-7"><p className="text-xs text-[#996800]">Unpublished preview · awaiting your approval</p><h4 className="mt-4 text-2xl font-semibold">{page.title}</h4>{page.content_blocks.map((block, index) => <section key={index} className="mt-5"><h5 className="font-semibold">{block.heading}</h5><p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{block.body}</p></section>)}{page.faqs.map(faq => <section key={faq.question} className="mt-5"><h5 className="font-semibold">{faq.question}</h5><p className="mt-2 text-sm leading-7">{faq.answer}</p></section>)}<p className="mt-6 inline-block rounded-lg bg-[#243e54] px-4 py-2 text-sm font-semibold text-white">{page.cta.label}</p></article>
    <div className="rounded-xl border border-white/10 p-5"><h4 className="text-sm font-semibold">Search listing</h4><p className="mt-3 text-lg text-sky-300">{page.seo.page_title}</p><p className="mt-2 text-sm leading-7 text-slate-300">{page.seo.meta_description}</p></div><p className="text-xs leading-6 text-muted-foreground">{page.asset_requirements.length} image instructions are included. Image permissions still need review. {outcome.next}</p>
  </section>;
}
