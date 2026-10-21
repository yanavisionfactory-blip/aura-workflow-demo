import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowUpRight, CheckCircle2, Download, FileText, FlaskConical, ShieldCheck } from 'lucide-react';
import { websiteContentZip } from '@/lib/websiteContentExport.mjs';
import { cmsToolScreenPath, websiteCMSPreview } from '@/lib/websiteCMSPreview.mjs';
import WebsiteCMSPreview from './WebsiteCMSPreview';

const panel = 'rounded-2xl border border-white/10 bg-[#101722] p-5 sm:p-6';
const muted = 'text-xs leading-6 text-muted-foreground';
const tabs = ['Pages', 'Changes', 'Approvals', 'Developer handoff', 'Tool results'];
const button = (active) => `rounded-lg border px-3 py-2 text-xs ${active ? 'border-primary/50 bg-primary/10 text-primary' : 'border-white/10 text-muted-foreground hover:text-foreground'}`;

function pageName(page) {
  const path = new URL(page.url).pathname;
  return path === '/' ? 'Home' : path.replaceAll('/', '').split('-').map((part) =>
    ['sat', 'ap'].includes(part) ? part.toUpperCase() : part.charAt(0).toUpperCase() + part.slice(1)
  ).join(' ');
}

function download(packet, filename = 'aura-five-page-content-package.json') {
  const url = URL.createObjectURL(new Blob([JSON.stringify(packet, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
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

function PageCopy({ page }) {
  return <article aria-label={`${page.page_id} revised page`} className="space-y-6">
    <header>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold">{pageName(page)}</h3>
        <a href={page.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-slate-300 hover:text-white">Existing live page<ArrowUpRight className="h-3.5 w-3.5"/></a>
      </div>
      <p className="mt-2 break-all font-mono text-[11px] text-muted-foreground">{page.url}</p>
      <p className="mt-3 text-sm leading-6 text-slate-300"><span className="font-medium text-slate-100">Purpose: </span>{page.purpose}</p>
    </header>
    <div className="overflow-hidden rounded-xl bg-[#f6f5f0] text-[#172536] shadow-lg">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-900/10 px-5 py-3 sm:px-8">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">Revised copy · unpublished review draft</p>
        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[10px] font-medium text-amber-900">Approval pending</span>
      </div>
      <div className="px-5 py-7 sm:px-8 sm:py-8">
        <h1 className="text-2xl font-semibold leading-tight tracking-tight sm:text-3xl">{page.h1}</h1>
        {page.sections.map((section, index) => <section key={index} className="mt-6"><h2 className="text-base font-semibold">{section.heading}</h2><p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-700">{section.body}</p></section>)}
        {page.faqs?.length > 0 && <section aria-label="Parent FAQs" className="mt-8 border-t border-slate-900/10 pt-6"><h2 className="text-lg font-semibold">Questions parents ask</h2><div className="mt-4 space-y-5">{page.faqs.map((faq) => <div key={faq.question}><h3 className="text-sm font-semibold">{faq.question}</h3><p className="mt-1 text-sm leading-7 text-slate-700">{faq.answer}</p></div>)}</div></section>}
        <div className="mt-7 inline-block rounded-lg bg-[#243e54] px-5 py-2.5 text-sm font-semibold text-white">{page.cta_label}</div>
        <p className="mt-3 break-all text-[11px] text-slate-500">CTA destination: {page.cta_target}</p>
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
    <div><h4 className="mb-3 text-sm font-semibold">Asset requirements</h4><div className="space-y-3">{page.assets.map((asset, index) => <div key={index} className="rounded-xl border border-white/10 p-4 text-xs leading-6"><p className="font-semibold">{asset.requirement}</p><p className="mt-1 text-amber-200">Rights: {asset.rights_status} · approval: {asset.approval_status}</p><p>Suggested alt text: {asset.alt_text}</p><p>Crop: {asset.crop}</p>{asset.candidate_url ? <a className="mt-2 block break-all text-primary" href={asset.candidate_url} target="_blank" rel="noopener noreferrer">Observed candidate image</a> : <p>New approved asset required</p>}</div>)}</div></div>
    <details className="rounded-xl border border-white/10 p-4"><summary className="cursor-pointer text-xs font-medium">Review notes &amp; version</summary><div className="mt-3"><Field label={`Version ${page.version}`}>{page.review_notes.join('\n')}</Field></div></details>
  </article>;
}

export default function WebsiteContentResult({ packet, runId = null, initialTab = 'Pages', initialPage, initialTool = 'content', initialSimulation = false, toolScreenHref = null, demoMode = false }) {
  const navigate = useNavigate();
  const resultsRef = useRef(null);
  const [tab, setTab] = useState(initialTab);
  const [pageId, setPageId] = useState(initialPage || packet.pages[0].page_id);
  const [tool, setTool] = useState(initialTool);
  const [simulation, setSimulation] = useState(() => initialSimulation || (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('cmsPreview') === 'simulated'));
  const preview = useMemo(() => simulation ? websiteCMSPreview(packet) : null, [simulation, packet]);
  const page = packet.pages.find((item) => item.page_id === pageId) || packet.pages[0];
  const sources = packet.sources;
  const sourceTools = [
    { id: 'website', name: 'Existing website & sitemap', detail: `${sources.filter((item) => item.source.role === 'page').length} pages read; sitemap and agency evidence saved` },
    { id: 'cms', name: packet.systems.find((item) => item.area === 'CMS')?.tool || 'CMS check', detail: 'Public CMS discovery; client write connection remains separate' },
    { id: 'files', name: 'Source files & approvals', detail: 'Client asset storage, approval and project-management tools still need confirmation' },
    { id: 'content', name: 'AURA content package', detail: 'Five complete revised pages, comparisons and handoff' },
  ];
  const tools = [...sourceTools, ...(preview?.tools || []).map((item) => ({ id: item.id, name: `${item.name} · simulated`, detail: item.summary }))];
  const previewTool = preview?.tools.find((item) => item.id === tool);
  const showPages = tab === 'Pages' || tab === 'Changes' || (tab === 'Tool results' && tool === 'content');
  const toolPath = (id) => toolScreenHref ? toolScreenHref(id) : cmsToolScreenPath(runId, id);
  const chooseTool = (id) => {
    const path = toolPath(id);
    if (path) { navigate(path); return; }
    if (id.endsWith('-preview')) setSimulation(true);
    setTool(id); setTab('Tool results'); window.requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };
  const toggleSimulation = () => {
    const next = !simulation;
    setSimulation(next);
    if (!next && tool.endsWith('-preview')) { setTool('content'); setTab('Pages'); }
    const url = new URL(window.location.href);
    if (next) url.searchParams.set('cmsPreview', 'simulated'); else url.searchParams.delete('cmsPreview');
    window.history.replaceState(window.history.state, '', url);
  };
  return <div aria-label="Five-page website content package">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-5">
      <div className="min-w-0 max-w-2xl">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">Website content / Ready for review</p>
        <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{packet.client}</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">Five-page content package prepared{simulation ? ' · CMS handoff simulation' : ''}</p>
      </div>
      <div className="flex flex-wrap gap-2"><button type="button" onClick={() => downloadCMS(packet)} className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-3 text-xs font-semibold text-white shadow-lg shadow-primary/10 hover:bg-primary/90"><Download className="h-4 w-4"/>Download CMS-ready files</button><button type="button" onClick={() => download(packet)} className="rounded-xl border border-white/10 px-4 py-3 text-xs text-muted-foreground hover:text-white">Download content package</button><a href="#website-tool-results" className="self-center px-2 py-2 text-xs text-primary">Explore results by tool ↓</a></div>
    </header>
    <section aria-label="Package status" className="mb-6 grid grid-cols-3 divide-x divide-white/10 rounded-xl border border-white/10 bg-card/40">
      {[['05', 'page drafts'], ['05', 'approvals pending'], ['00', 'live pages changed']].map(([value, label]) => <div key={label} className="px-3 py-4 sm:px-5"><span className="block text-2xl font-semibold tabular-nums sm:inline">{value}</span><span className="text-[11px] text-muted-foreground sm:ml-3">{label}</span></div>)}
    </section>
    <div className="mb-6 flex items-start gap-3 rounded-xl border border-amber-300/15 bg-amber-300/[0.04] px-4 py-3">
      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-200"/>
      <p className="text-xs leading-6 text-slate-300">Review drafts based on public sources. <span className="text-amber-200">Client brief, asset rights and named approver require confirmation.</span> CMS staging awaits approval.</p>
    </div>
    <section ref={resultsRef} className="mb-6 overflow-hidden rounded-2xl border border-white/10 bg-[#101722]" aria-label={simulation ? 'Results — content and simulated tool outputs' : 'Results — the actual output'}>
      <h3 className="sr-only">{simulation ? 'Results — content and simulated tool outputs' : 'Results — the actual output'}</h3>
      <div role="tablist" aria-label="Content package views" className="flex gap-1 overflow-x-auto border-b border-white/10 px-3 pt-2 sm:px-5">{tabs.map((name) => <button key={name} role="tab" aria-selected={tab === name} onClick={() => setTab(name)} className={`shrink-0 border-b-2 px-3 py-3 text-xs font-medium transition-colors ${tab === name ? 'border-primary text-white' : 'border-transparent text-muted-foreground hover:text-white'}`}>{name}</button>)}</div>
      <div className={showPages ? 'grid min-w-0 md:grid-cols-[200px_minmax(0,1fr)]' : ''}>
        {showPages && <nav aria-label="Select a page" className="flex gap-2 overflow-x-auto border-b border-white/10 bg-black/10 p-3 md:block md:space-y-1 md:border-b-0 md:border-r md:p-4">
          <p className="mb-3 hidden px-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground md:block">Pages / {packet.pages.length}</p>
          {packet.pages.map((item, index) => <button key={item.page_id} type="button" aria-label={`${item.page_id} · ${pageName(item)}`} aria-pressed={pageId === item.page_id} onClick={() => setPageId(item.page_id)} className={`flex min-w-36 items-start gap-3 rounded-lg border p-3 text-left transition-colors md:w-full md:min-w-0 ${pageId === item.page_id ? 'border-primary/30 bg-primary/10 text-white' : 'border-transparent text-slate-400 hover:bg-white/5 hover:text-white'}`}><span className="mt-0.5 text-[10px] tabular-nums text-muted-foreground">{String(index + 1).padStart(2, '0')}</span><span><span className="block text-xs font-medium leading-5">{pageName(item)}</span><span className="mt-1 block text-[10px] text-amber-200/70">Pending review</span></span></button>)}
        </nav>}
        <div role="tabpanel" aria-label={tab} className="min-w-0 p-4 sm:p-6">
        {tab === 'Tool results' && <div className="mb-5 flex flex-wrap gap-2" role="group" aria-label="Select tool result">{tools.map((item) => <button type="button" key={item.id} aria-pressed={tool === item.id} className={button(tool === item.id)} onClick={() => item.id.endsWith('-preview') ? chooseTool(item.id) : setTool(item.id)}>{item.name}</button>)}</div>}
        {(tab === 'Pages' || (tab === 'Tool results' && tool === 'content')) && <PageCopy page={page}/>}
        {tab === 'Changes' && <div className="space-y-5"><Field label="Page">{page.url}</Field>{page.marketing_changes?.length > 0 && <section aria-label="Major marketing changes"><h4 className="mb-3 text-sm font-semibold">Major marketing changes</h4><div className="space-y-3">{page.marketing_changes.map((change, index) => <div key={index} className="rounded-xl border border-white/10 p-4"><h5 className="text-sm font-semibold text-primary">{change.area}</h5><div className="mt-3 grid gap-4 sm:grid-cols-2"><div><p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Before</p><p className="mt-1 text-xs leading-6 text-slate-400">{change.before}</p></div><div><p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">After</p><p className="mt-1 text-xs leading-6 text-slate-200">{change.after}</p></div></div><p className="mt-3 border-t border-white/10 pt-3 text-xs leading-6 text-slate-300"><span className="font-semibold">Marketing reason: </span>{change.reason}</p></div>)}</div></section>}<div className="grid gap-5 sm:grid-cols-2"><Field label="Current copy excerpt · source snapshot">{page.original.excerpt}</Field><Field label="Revised message">{page.h1}{'\n\n'}{page.sections[0].body}</Field></div><Field label="Why this changed">{page.change_reason}</Field><div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b border-white/10"><th className="p-3">Field</th><th className="p-3">Current</th><th className="p-3">Revised</th></tr></thead><tbody>{[['Page title', page.original.title, page.page_title], ['Meta description', page.original.description || 'Absent in fetched HTML', page.meta_description], ['URL', page.url, 'Retain existing URL'], [demoMode ? 'Selected source headings' : 'Headings', page.original.headings.filter((heading) => heading.level <= 2).map((heading) => `H${heading.level} ${heading.text}`).join('\n'), `H1 ${page.h1}\n${page.sections.map((section) => `H2 ${section.heading}`).join('\n')}`]].map(([label, before, after]) => <tr key={label} className="border-b border-white/5"><th className="p-3 align-top">{label}</th><td className="whitespace-pre-wrap p-3 align-top text-slate-400">{before}</td><td className="whitespace-pre-wrap p-3 align-top text-slate-200">{after}</td></tr>)}</tbody></table></div><p className={muted}>Source {page.source_id} · sitemap membership: {page.sitemap_member ? 'found' : 'not confirmed'} · source timestamp and hash are in Tool results.</p></div>}
        {tab === 'Approvals' && <div><p className="mb-5 text-sm leading-7 text-amber-200">Every page is awaiting approval of its exact version. Reviewers and dates are empty until an actual decision is recorded. Running the workflow does not approve its content.</p><div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr>{['Page', 'Version', 'Copy', 'Assets/rights', 'Reviewer', 'Decision evidence', 'CMS draft'].map((label) => <th key={label} className="p-3">{label}</th>)}</tr></thead><tbody>{packet.pages.map((item) => <tr key={item.page_id} className="border-t border-white/10"><th className="p-3">{item.page_id}</th><td className="p-3 font-mono">{item.version}</td><td className="p-3">Pending</td><td className="p-3">Pending</td><td className="p-3">{item.approval.reviewer || 'Unassigned'}</td><td className="p-3">{item.approval.evidence || 'None'}</td><td className="p-3">Not created</td></tr>)}</tbody></table></div></div>}
        {tab === 'Developer handoff' && <div className="space-y-5"><Field label="Delivery">Structured JSON package · {packet.staging.reason}</Field><ol className="space-y-3">{packet.handoff.map((item, index) => <li key={item} className="flex gap-3 text-sm leading-7"><span className="font-semibold text-primary">{index + 1}.</span>{item}</li>)}</ol><Field label="Field mapping">URL → existing route reference; H1 → page heading; sections → H2/body blocks; CTA → label and verified destination; page_title/meta_description → SEO fields; assets → approved attachment IDs after rights review. Preserve the source URL and version in the staging manifest.</Field><div className="flex flex-wrap gap-3"><button type="button" onClick={() => downloadCMS(packet)} className="rounded-lg border border-primary/40 px-4 py-2 text-xs text-primary">Download HTML &amp; metadata</button><button type="button" onClick={() => download(packet)} className="rounded-lg border border-white/10 px-4 py-2 text-xs text-muted-foreground">Download structured handoff</button></div></div>}
        {tab === 'Tool results' && <div>
          {previewTool && <WebsiteCMSPreview key={previewTool.id} output={previewTool}/>}
          {tool === 'content' && <div className="mt-6 rounded-xl border border-white/10 p-4"><p className="flex items-center gap-2 text-sm font-semibold"><CheckCircle2 className="h-4 w-4 text-emerald-400"/>{demoMode ? 'Saved content generation snapshot' : 'AURA model generation executed'}</p><p className={muted}>{packet.execution.executed_at} · {packet.execution.model} · {packet.execution.model_attempts} model call(s)</p><p className="mt-2 break-all font-mono text-[10px] text-muted-foreground">Receipt {packet.execution.id}</p></div>}
          {(tool === 'website' || tool === 'cms') && <div className="space-y-4">{sources.filter((item) => tool === 'cms' ? item.source.role === 'cms' : item.source.role !== 'cms').map(({ source, receipt }) => <div key={source.key} className="rounded-xl border border-white/10 p-4"><p className="text-sm font-semibold">{source.key} · {source.title || source.role}</p><a className="mt-2 block break-all text-xs text-primary" href={source.url} target="_blank" rel="noopener noreferrer">{source.url}</a><p className={muted}>GET · HTTP {receipt.status} · {receipt.fetched_at} · {receipt.bytes.toLocaleString()} bytes</p><p className="mt-2 break-all font-mono text-[10px] text-muted-foreground">Receipt {receipt.id} · SHA-256 {receipt.sha256}</p>{source.cms && <p className="mt-3 text-sm text-emerald-300">{source.cms} detected through its public REST namespace on the selected origin. This is not authenticated draft access.</p>}{source.role === 'sitemap' && <div className="mt-3"><p className={muted}>{source.urls.length} sitemap URLs read</p><ul className="mt-2 space-y-1 text-xs">{packet.pages.map((item) => <li key={item.page_id}>{item.page_id}: {item.sitemap_member ? 'Found in sitemap' : 'Membership unconfirmed'}</li>)}</ul></div>}{source.role === 'page' && <p className="mt-3 text-xs leading-6 text-slate-300">Current source excerpt: {source.excerpt}</p>}</div>)}</div>}
          {tool === 'files' && <div className="space-y-5"><Field label="Working brief">{packet.working_brief}{'\n\n'}{packet.brief_status}</Field>{packet.systems.map((system) => <div key={system.area} className="rounded-xl border border-white/10 p-4"><p className="text-sm font-semibold">{system.area} · {system.tool}</p><p className="mt-2 text-xs text-amber-200">{system.status}</p><p className={muted}>{system.detail}</p></div>)}<details className="rounded-xl border border-white/10 p-4"><summary className="cursor-pointer text-xs font-semibold">Actual source-file discovery response</summary><pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs">{Object.keys(packet.discovery).length ? JSON.stringify(packet.discovery, null, 2) : 'No connected native Drive search capability was selected. Client storage adoption remains unconfirmed.'}</pre></details></div>}
        </div>}
        </div>
      </div>
    </section>
    <section id="website-tool-results" aria-label="What happened" className="mb-6">
      <h3 className="mb-3 text-base font-semibold">Results by tool</h3><p className="mb-4 text-xs leading-6 text-muted-foreground">What happened in each source, followed by the simulated CMS handoffs.</p>
      <div className="space-y-2">{sourceTools.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-card/30 px-4 py-3"><div className="flex min-w-0 items-start gap-3"><ShieldCheck className={`mt-0.5 h-4 w-4 shrink-0 ${item.id === 'files' ? 'text-amber-300' : 'text-emerald-400'}`}/><span><span className="block text-sm font-medium">{item.name}</span><span className="mt-1 block text-xs leading-5 text-muted-foreground">{item.detail}</span></span></div><button type="button" onClick={() => chooseTool(item.id === 'cms' && simulation ? 'wordpress-preview' : item.id)} aria-label={`View ${item.name} result`} className="shrink-0 rounded-full border border-primary/30 px-3 py-1.5 text-xs text-primary">{item.id === 'cms' && simulation ? 'View in WordPress' : item.id === 'content' ? 'View content package' : 'View details'}<ArrowUpRight className="ml-1 inline h-3 w-3"/></button></div>)}</div>
    </section>
    <section aria-label="CMS output simulation" className="mb-6 rounded-2xl border border-violet-300/20 bg-violet-300/[0.025] p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="flex items-center gap-2 text-sm font-semibold"><FlaskConical className="h-4 w-4 text-violet-300"/>CMS handoff demo</h3><p className="mt-2 max-w-2xl text-xs leading-6 text-muted-foreground">Preview the complete output from each CMS using these five saved page drafts.</p></div><button type="button" aria-pressed={simulation} onClick={toggleSimulation} className="rounded-lg border border-violet-300/30 px-3 py-2 text-xs font-medium text-violet-200">{simulation ? 'Hide simulated outputs' : 'Preview simulated CMS outputs'}</button></div>
      {!simulation && <div aria-label="Shopify simulation preview" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#101722] px-4 py-4">
        <div className="flex min-w-0 items-start gap-3"><FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-violet-300"/><div><p className="flex items-center gap-2 text-sm font-semibold">Shopify<span className="rounded-full bg-violet-300/10 px-2 py-0.5 text-[10px] font-medium text-violet-300">Simulated</span></p><p className="mt-1 text-xs leading-6 text-slate-300">Explore all five saved page drafts in a simulated Shopify admin.</p><p className="mt-1 text-[11px] text-muted-foreground">Preview only · no Shopify account connected or records created</p></div></div>
        <Link to={toolPath('shopify-preview') || '#'} onClick={(event) => { if (!toolPath('shopify-preview')) { event.preventDefault(); chooseTool('shopify-preview'); } }} className="rounded-full border border-primary/30 px-3 py-1.5 text-xs text-primary">View in Shopify<ArrowUpRight className="ml-1 inline h-3 w-3"/></Link>
      </div>}
      {preview && <>
        <p role="status" className="mt-4 rounded-lg border border-violet-300/20 bg-violet-300/10 px-4 py-3 text-xs leading-6 text-violet-200"><strong>Simulation mode.</strong> WordPress, Shopify, WooCommerce and BigCommerce outputs below are local previews. No CMS API calls, records, approvals or live changes were made. The real source reads and content generation remain in the workflow evidence.</p>
        <div className="mt-4 space-y-2">{preview.tools.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#101722] px-4 py-4"><div className="flex min-w-0 items-start gap-3"><FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-violet-300"/><span><span className="flex flex-wrap items-center gap-2 text-sm font-semibold">{item.name}<span className="rounded-full bg-violet-300/10 px-2 py-0.5 text-[10px] font-medium text-violet-300">Simulated</span></span><span className="mt-1 block text-xs text-slate-300">{item.summary}</span><span className="mt-1 block text-[11px] text-muted-foreground">{item.scope} · 0 remote records</span></span></div><Link to={toolPath(item.id) || '#'} aria-label={`View in ${item.name}`} onClick={(event) => { if (!toolPath(item.id)) { event.preventDefault(); chooseTool(item.id); } }} className="rounded-full border border-primary/30 px-3 py-1.5 text-xs text-primary">View in {item.name}<ArrowUpRight className="ml-1 inline h-3 w-3"/></Link></div>)}</div>
        <button type="button" onClick={() => download(preview, 'aura-simulated-cms-tool-outputs.json')} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300"><Download className="h-3.5 w-3.5"/>Download simulated tool outputs</button>
      </>}
    </section>
    <section aria-label="Tools used and previewed" className="mb-6 rounded-xl border border-white/10 bg-card/30 p-4"><h3 className="text-xs font-semibold">Tools used{simulation ? ' & simulated outputs' : ''}</h3><div className="mt-3 flex flex-wrap gap-2">{tools.map((item) => <button type="button" key={item.id} onClick={() => chooseTool(item.id)} className="rounded-lg border border-white/10 px-2.5 py-1.5 text-[11px] text-slate-300 hover:border-primary/40">{item.name}</button>)}</div></section>
    <details className={`${panel} mb-6`}>
      <summary className="cursor-pointer text-sm font-medium">Sources &amp; workflow evidence <span className="ml-2 text-xs font-normal text-muted-foreground">{sources.length} source snapshots</span></summary>
      <p className="mt-4 text-xs leading-6 text-slate-400">{packet.summary}</p>
      <p className="mt-2 text-xs leading-6 text-slate-400">{demoMode ? 'This separate demo replays a saved package based on public website, sitemap and CMS evidence. No live provider calls occur in this demo.' : 'AURA fetched the public website, sitemap and CMS evidence, then generated this content package.'} No CMS draft, external ticket, message, publish or schedule action ran.</p>
      <div aria-label="Results per tool" className="mt-4 grid gap-2 sm:grid-cols-2">{sourceTools.map((item) => <button key={item.id} type="button" onClick={() => chooseTool(item.id)} aria-label={`View ${item.name} result`} className="flex items-center gap-3 rounded-lg border border-white/10 p-3 text-left hover:border-primary/50"><FileText className="h-4 w-4 shrink-0 text-primary"/><span className="min-w-0 flex-1"><span className="block text-xs font-medium">{item.name}</span><span className="mt-1 block text-[11px] leading-5 text-muted-foreground">{item.detail}</span></span><ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground"/></button>)}</div>
    </details>
  </div>;
}
