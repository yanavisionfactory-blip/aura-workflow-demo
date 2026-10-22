import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowUpRight, Download, FlaskConical, ShieldCheck } from 'lucide-react';
import { websiteContentZip } from '@/lib/websiteContentExport.mjs';
import { cmsToolScreenPath, websiteCMSPreview } from '@/lib/websiteCMSPreview.mjs';
import WebsiteCMSPreview from './WebsiteCMSPreview';
import { websiteToolOutcome } from '@/lib/websiteToolOutcomes.mjs';

const tabs = ['Pages', 'Changes', 'Approvals', 'Developer handoff'];

function pageName(page) {
  const path = new URL(page.url).pathname;
  return path === '/' ? 'Home' : path.replaceAll('/', '').split('-').map((part) =>
    ['sat', 'ap'].includes(part) ? part.toUpperCase() : part.charAt(0).toUpperCase() + part.slice(1)
  ).join(' ');
}

function downloadCMS(packet) {
  const url = URL.createObjectURL(new Blob([websiteContentZip(packet)], { type: 'application/zip' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = 'aura-five-page-cms-ready.zip'; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Field({ label, children }) {
  return <div><h4 className="text-xs font-semibold text-primary">{label}</h4><div className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-200">{children}</div></div>;
}

function PageCopy({ page, demoApproval = false }) {
  return <article aria-label={`${pageName(page)} revised page`} className="space-y-6">
    <header>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold">{pageName(page)}</h3>
        <a href={page.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-slate-300 hover:text-white">Existing live page<ArrowUpRight className="h-3.5 w-3.5"/></a>
      </div>
      <p className="mt-2 break-all font-mono text-[11px] text-muted-foreground">{page.url}</p>
      <p className="mt-3 text-sm leading-6 text-slate-300"><span className="font-medium text-slate-100">What this page should achieve: </span>{page.purpose}</p>
    </header>
    <div className="overflow-hidden rounded-xl bg-[#f6f5f0] text-[#172536] shadow-lg">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-900/10 px-5 py-3 sm:px-8">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">Revised copy · unpublished review draft</p>
        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[10px] font-medium text-amber-900">{demoApproval ? 'Demo approved · unpublished' : 'Approval pending'}</span>
      </div>
      <div className="px-5 py-7 sm:px-8 sm:py-8">
        <h1 className="text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">{page.h1}</h1>
        {page.sections.map((section, index) => <section key={index} className="mt-6"><h2 className="text-base font-semibold">{section.heading}</h2><p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{section.body}</p></section>)}
        {page.faqs?.length > 0 && <section aria-label="Parent FAQs" className="mt-8 border-t border-slate-900/10 pt-6"><h2 className="text-lg font-semibold">Questions parents ask</h2><div className="mt-4 space-y-5">{page.faqs.map((faq) => <div key={faq.question}><h3 className="text-sm font-semibold">{faq.question}</h3><p className="mt-1 text-sm leading-7 text-slate-700">{faq.answer}</p></div>)}</div></section>}
        <div className="mt-7 inline-block rounded-lg bg-[#243e54] px-5 py-2.5 text-sm font-semibold text-white">{page.cta_label}</div>
        <p className="mt-3 break-all text-[11px] text-slate-500">Button opens: {page.cta_target}</p>
        {page.internal_links?.length > 0 && <nav aria-label="Proposed internal links" className="mt-6 border-t border-slate-900/10 pt-5"><h2 className="text-sm font-semibold">Explore related support</h2><ul className="mt-3 space-y-2">{page.internal_links.map((link) => <li key={link.url}><a href={link.url} target="_blank" rel="noopener noreferrer" className="text-sm text-sky-800 underline underline-offset-4">{link.label}</a><p className="mt-1 text-[11px] leading-5 text-slate-500">{link.reason}</p></li>)}</ul></nav>}
      </div>
    </div>
    <section aria-label="Search preview" className="rounded-xl border border-white/10 p-5">
      <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Search preview</p>
      <p className="text-lg text-sky-300">{page.page_title}</p>
      <p className="mt-1 break-all text-[11px] text-emerald-300">{page.url}</p>
      <p className="mt-2 text-sm leading-6 text-slate-300">{page.meta_description}</p>
      <p className="mt-4 border-t border-white/10 pt-3 text-[11px] text-muted-foreground">Page title · {[...page.page_title].length} characters <span className="mx-2">/</span> Meta description · {[...page.meta_description].length} characters</p>
    </section>
    <div><h4 className="mb-3 text-sm font-semibold">Images to prepare</h4><div className="space-y-3">{page.assets.map((asset, index) => <div key={index} className="rounded-xl border border-white/10 p-4 text-xs leading-6"><p className="font-semibold">{asset.requirement}</p><p className="mt-1 text-amber-200">{demoApproval ? 'Sample image manifest approved for this simulation. Real image rights remain unconfirmed.' : 'Image permissions and approval still need review.'}</p><p>Description for screen readers: {asset.alt_text}</p><p>Suggested framing: {asset.crop}</p>{asset.candidate_url ? <a className="mt-2 block break-all text-primary" href={asset.candidate_url} target="_blank" rel="noopener noreferrer">Reference image from the current website</a> : <p>Choose an approved image before publishing.</p>}</div>)}</div></div>
    <details className="rounded-xl border border-white/10 p-4"><summary className="cursor-pointer text-xs font-medium">Before you approve this page</summary><ul className="mt-3 space-y-2 text-sm leading-7 text-slate-300">{page.review_notes.map(note => <li key={note}>{note}</li>)}</ul></details>
  </article>;
}

export default function WebsiteContentResult({ packet, runId = null, initialTab = 'Pages', initialPage, initialTool = 'content', toolScreenHref = null, demoMode = false, toolOutputs = null, demoApproval = false }) {
  const navigate = useNavigate();
  const outcomesRef = useRef(null);
  const [tab, setTab] = useState(tabs.includes(initialTab) ? initialTab : 'Pages');
  const [pageId, setPageId] = useState(initialPage || packet.pages[0].page_id);
  const [selectedTool, setSelectedTool] = useState(initialTool.endsWith('-preview') ? initialTool : null);
  const preview = useMemo(() => toolOutputs ? { tools: toolOutputs } : websiteCMSPreview(packet), [packet, toolOutputs]);
  const page = packet.pages.find(item => item.page_id === pageId) || packet.pages[0];
  const inlineOutput = preview.tools.find(item => item.id === selectedTool);
  const showPages = tab === 'Pages' || tab === 'Changes';
  const toolPath = id => toolScreenHref ? toolScreenHref(id) : cmsToolScreenPath(runId, id);
  const chooseTool = id => {
    const path = toolPath(id);
    if (path) { navigate(path); return; }
    setSelectedTool(id);
    window.requestAnimationFrame(() => outcomesRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };
  return <div aria-label="Five-page website content package">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-5">
      <div className="min-w-0 max-w-2xl"><p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">Website content · Ready for your review</p><h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{packet.client}</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Your five-page content package: revised copy, search listings, buttons and image instructions.</p></div>
      <div className="flex flex-wrap gap-3"><button type="button" onClick={() => downloadCMS(packet)} className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-3 text-xs font-semibold text-white"><Download className="h-4 w-4"/>Download website files</button><a href="#website-tool-results" className="self-center px-2 py-2 text-xs text-primary">Explore results by tool ↓</a></div>
    </header>
    <section aria-label="Package status" className="mb-6 grid grid-cols-3 divide-x divide-white/10 rounded-xl border border-white/10 bg-card/40">{[[String(packet.pages.length).padStart(2, '0'), 'page drafts'], [String(packet.pages.length).padStart(2, '0'), demoApproval ? 'sample pages approved' : 'approvals pending'], ['00', 'live pages changed']].map(([value, label]) => <div key={label} className="px-3 py-4 sm:px-5"><span className="block text-2xl font-semibold sm:inline">{value}</span><span className="text-[11px] text-muted-foreground sm:ml-3">{label}</span></div>)}</section>
    <p className="mb-6 flex items-start gap-3 rounded-xl border border-amber-300/15 bg-amber-300/[0.04] px-4 py-3 text-xs leading-6 text-slate-300"><ShieldCheck className="mt-1 h-4 w-4 shrink-0 text-amber-200"/><span>{demoApproval ? 'Sample copy and image manifest approved for this simulation only. Real client approvals, asset rights and publishing access remain unconfirmed.' : 'Review the copy and image permissions with your client. The client-approved brief, named reviewer and publishing destination still need confirmation.'}</span></p>
    <section aria-label="Main content result" className="mb-8 overflow-hidden rounded-2xl border border-white/10 bg-[#101722]">
      <div role="tablist" aria-label="Content package views" className="flex gap-1 overflow-x-auto border-b border-white/10 px-3 pt-2 sm:px-5">{tabs.map(name => <button key={name} role="tab" aria-selected={tab === name} onClick={() => setTab(name)} className={`shrink-0 border-b-2 px-3 py-3 text-xs font-medium ${tab === name ? 'border-primary text-white' : 'border-transparent text-muted-foreground hover:text-white'}`}>{name}</button>)}</div>
      <div className={showPages ? 'grid min-w-0 md:grid-cols-[200px_minmax(0,1fr)]' : ''}>
        {showPages && <nav aria-label="Select a page" className="flex gap-2 overflow-x-auto border-b border-white/10 bg-black/10 p-3 md:block md:space-y-1 md:border-b-0 md:border-r md:p-4"><p className="mb-3 hidden px-2 text-[10px] uppercase tracking-widest text-muted-foreground md:block">Your pages</p>{packet.pages.map((item, index) => <button key={item.page_id} type="button" aria-label={pageName(item)} aria-pressed={pageId === item.page_id} onClick={() => setPageId(item.page_id)} className={`flex min-w-36 items-start gap-3 rounded-lg border p-3 text-left md:w-full md:min-w-0 ${pageId === item.page_id ? 'border-primary/30 bg-primary/10 text-white' : 'border-transparent text-slate-400 hover:bg-white/5'}`}><span className="mt-0.5 text-[10px] text-muted-foreground">{index + 1}</span><span><span className="block text-xs font-medium leading-5">{pageName(item)}</span><span className="mt-1 block text-[10px] text-amber-200/70">{demoApproval ? 'Demo approved' : 'Awaiting review'}</span></span></button>)}</nav>}
        <div role="tabpanel" aria-label={tab} className="min-w-0 p-4 sm:p-6">
          {tab === 'Pages' && <PageCopy page={page} demoApproval={demoApproval}/>}
          {tab === 'Changes' && <div className="space-y-5"><h3 className="text-lg font-semibold">What changed on {pageName(page)}</h3>{page.marketing_changes?.length > 0 && <section aria-label="Major marketing changes" className="space-y-3">{page.marketing_changes.map((change, index) => <div key={index} className="rounded-xl border border-white/10 p-4"><h4 className="font-semibold text-primary">{change.area}</h4><p className="mt-2 text-sm leading-7"><strong>Before: </strong>{change.before}</p><p className="mt-2 text-sm leading-7"><strong>After: </strong>{change.after}</p><p className="mt-2 text-xs leading-6 text-slate-300"><strong>Why: </strong>{change.reason}</p></div>)}</section>}<div className="grid gap-5 sm:grid-cols-2"><Field label="Before · excerpt from the existing website">{page.original.excerpt}</Field><Field label="After · revised introduction">{page.h1}{'\n\n'}{page.sections[0].body}</Field></div><Field label="Why this helps">{page.change_reason}</Field><div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-3">Part of the page</th><th className="p-3">Before</th><th className="p-3">After</th></tr></thead><tbody>{[['Search title', page.original.title, page.page_title], ['Search description', page.original.description || 'No description found', page.meta_description], ['Page address', page.url, 'Keep the existing address'], [demoMode ? 'Selected page headings' : 'Page headings', page.original.headings.filter(heading => heading.level <= 2).map(heading => heading.text).join('\n'), [page.h1, ...page.sections.map(section => section.heading)].join('\n')]].map(([label, before, after]) => <tr key={label} className="border-t border-white/10"><th className="p-3 align-top">{label}</th><td className="whitespace-pre-wrap p-3 align-top text-slate-400">{before}</td><td className="whitespace-pre-wrap p-3 align-top text-slate-200">{after}</td></tr>)}</tbody></table></div></div>}
          {tab === 'Approvals' && <div><h3 className="text-lg font-semibold">What needs your approval</h3><p className="my-4 text-sm leading-7 text-slate-300">{demoApproval ? 'All five sample versions and the sample image manifest were approved by the demo reviewer for this simulation only. Actual client approvals remain pending.' : 'Review each page’s copy and image permissions, then choose a reviewer. These drafts are awaiting a decision.'}</p><div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr>{['Page', 'Copy review', 'Image permissions', 'Reviewer', 'Next step'].map(label => <th key={label} className="p-3">{label}</th>)}</tr></thead><tbody>{packet.pages.map(item => <tr key={item.page_id} className="border-t border-white/10"><th className="p-3">{pageName(item)}</th><td className="p-3 text-amber-200">{demoApproval ? 'Demo approved' : 'Pending'}</td><td className="p-3 text-amber-200">{demoApproval ? 'Demo approved' : 'Pending'}</td><td className="p-3">{demoApproval ? 'Demo reviewer — simulated role' : item.approval.reviewer || 'Choose a reviewer'}</td><td className="p-3">{demoApproval ? 'Inspect the simulated draft readbacks' : 'Review copy and images'}</td></tr>)}</tbody></table></div></div>}
          {tab === 'Developer handoff' && <div className="space-y-6"><h3 className="text-lg font-semibold">Ready to hand over</h3><div className="grid gap-3 sm:grid-cols-3">{['Five complete page drafts', 'Search listings and buttons', 'Image instructions for each page'].map(label => <p key={label} className="rounded-xl border border-white/10 p-4 text-sm leading-6">{label}</p>)}</div><Field label="Before your developer starts">{demoApproval ? 'The simulation created and checked 20 unpublished sample drafts across four alternative CMS destinations. Download the files for the content and execution record. A real handoff still needs client approval, image rights and a verified destination.' : 'Approve the copy, confirm image permissions and choose the website or store that will receive the pages.'}</Field><Field label="How to use the website files">Each page includes the revised text, headings, search title and description, button destination and image instructions. Ask your developer to create separate unpublished drafts after approval and keep your current pages live.</Field><div className="rounded-xl border border-white/10 p-4"><h4 className="text-sm font-semibold">Confirm the client’s tools separately</h4><dl className="mt-3 space-y-3 text-xs leading-6">{packet.systems.map(system => <div key={system.area} className="sm:flex sm:gap-5"><dt className="font-semibold sm:w-36 sm:shrink-0">{system.area}</dt><dd className="text-slate-300">{system.area === 'CMS' ? `${system.tool} is evidenced by the existing website. Confirm the correct client account before adding drafts.` : system.area === 'Asset storage' ? 'Confirm where the approved images and brand files are kept.' : system.area === 'Approval' ? 'Confirm who reviews the pages and where they record approval.' : 'Confirm where the developer handoff should be tracked.'}</dd></div>)}</dl></div><button type="button" onClick={() => downloadCMS(packet)} className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-3 text-xs font-semibold"><Download className="h-4 w-4"/>Download website files for your developer</button></div>}
        </div>
      </div>
    </section>
    {preview.tools.length > 0 && <section id="website-tool-results" aria-label="Simulated tool outcomes" className="mb-6 scroll-mt-6">
      <h3 className="text-xl font-semibold">Results by tool</h3><p className="mt-3 max-w-3xl text-sm leading-7 text-slate-300">{demoApproval ? 'AURA executed four local CMS adapters with the approved sample package. Each created five separate unpublished records and read them back successfully. These are alternative destination tests for the same five pages.' : 'AURA prepared the copy above. These four simulated outcomes show how the same package would be prepared for each website or store. They are alternative destinations for this task.'}</p><p className="mt-3 flex items-center gap-2 text-xs leading-6 text-violet-300"><FlaskConical className="h-4 w-4 shrink-0"/>{demoApproval ? 'Executed simulation only. Twenty local test records; no real accounts or live pages changed.' : 'Simulated previews only. No pages have been added to a real account or published.'}</p>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">{preview.tools.map(item => { const outcome = websiteToolOutcome(item.name); return <article key={item.id} aria-label={`${item.name} task outcome`} className="flex flex-col rounded-2xl border border-white/10 bg-[#101722] p-5 sm:p-6"><header className="flex flex-wrap items-center justify-between gap-3"><h4 className="text-lg font-semibold">{item.name}</h4><span className="rounded-full bg-violet-300/10 px-3 py-1 text-[10px] font-semibold text-violet-300">Simulated</span></header><p className="mt-2 text-xs text-muted-foreground">{outcome.destination}</p><p className="mt-5 text-[10px] font-semibold uppercase tracking-widest text-primary">Part of your task</p><h5 className="mt-2 text-base font-semibold leading-6">{outcome.part}</h5><p className="mt-3 text-sm leading-7 text-slate-300">{item.status === 'simulated_drafts_verified' ? 'Five unpublished sample drafts created and read back. All five checks passed.' : outcome.result}</p><ul className="mt-4 space-y-2 text-xs leading-6 text-slate-300">{outcome.includes.map(line => <li key={line} className="flex gap-2"><span className="text-emerald-300">✓</span>{line}</li>)}</ul><p className="mt-5 border-t border-white/10 pt-4 text-xs leading-6 text-muted-foreground"><strong className="text-slate-300">Your next step: </strong>{item.status === 'simulated_drafts_verified' ? 'Inspect the checked drafts below. Confirm actual client approval and account access before any real staging.' : outcome.next}</p><Link to={toolPath(item.id) || '#'} onClick={event => { if (!toolPath(item.id)) { event.preventDefault(); chooseTool(item.id); } }} className="mt-5 self-start rounded-full border border-primary/30 px-4 py-2 text-xs font-medium text-primary">View in {item.name}<ArrowUpRight className="ml-1 inline h-3 w-3"/></Link></article>; })}</div>
      {inlineOutput && <div ref={outcomesRef} className="mt-6"><WebsiteCMSPreview key={inlineOutput.id} output={inlineOutput}/></div>}
    </section>}
  </div>;
}
