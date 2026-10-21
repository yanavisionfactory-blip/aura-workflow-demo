import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Activity, AlertCircle, ArrowRight, Check, CheckCircle2, ChevronDown, Download, ExternalLink, Loader2, ShieldCheck, Upload } from "lucide-react";
import PrimaryResult from "@/components/aura/PrimaryResult";
import ArticleResultPreview from "@/components/aura/ArticleResultPreview";
import DeliverySourceLinks from "@/components/aura/DeliverySourceLinks";
import CampaignDeliveryView from "@/components/aura/CampaignDeliveryView";
import MarketingDeliveryView from "@/components/aura/MarketingDeliveryView";
import { parseMarketingDelivery } from "@/lib/marketingToolResults.mjs";
import { parseCampaignDelivery } from "@/lib/campaignDelivery.mjs";
import WorkspaceShell from "@/components/aura/WorkspaceShell";
import { ResultsHeading, ResultsMetrics } from "@/components/aura/ResultsSummary";
import { aura } from "@/api/auraClient";
import { articleMarkdown } from "@/lib/actionContent.mjs";
import { deliveryLink, deliveryMetrics, deliverySections, deliveryToolLinks, parseDeliveryBundle } from "@/lib/workflowDelivery.mjs";

const stamp = (value) => value ? new Date(value).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC" : "Recorded in source";
const card = "rounded-2xl border border-white/10 bg-card/60";
const parseResults = (text) => { const data = JSON.parse(text); return data.kind === "marketing_tools" ? parseMarketingDelivery(data) : data.kind === "campaign_launch" ? parseCampaignDelivery(data) : parseDeliveryBundle(text); };

async function downloadReview(data) {
  const { jsPDF } = await import("jspdf");
  const pdf = new jsPDF({ unit: "pt", format: "a4" });
  let y = 62;
  const width = 475;
  const page = () => { pdf.addPage(); y = 62; };
  const write = (text, size = 10, bold = false) => {
    pdf.setFont("helvetica", bold ? "bold" : "normal"); pdf.setFontSize(size);
    const plain = articleMarkdown(String(text)).replace(/^#{1,6}\s*/gm, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/[*_]/g, "").replace(/[—–]/g, "-").replace(/[‘’]/g, "'").replace(/[“”]/g, '"');
    for (const line of pdf.splitTextToSize(plain, width)) { if (y > 770) page(); pdf.text(line, 60, y); y += size * 1.5; }
    y += 10;
  };
  pdf.setTextColor(92, 75, 210); write(`AURA / ${data.agency || "AGENCY REVIEW"}`, 11, true);
  pdf.setTextColor(22, 29, 43); write(data.title, 23, true); write(data.summary, 11);
  write("Fictional client demonstration. Every article remains unpublished. No outgoing messages were sent.");
  for (const [title, body] of deliverySections(data)) { if (y > 700) page(); write(title, 15, true); write(body); }
  const pages = pdf.getNumberOfPages();
  for (let i = 1; i <= pages; i++) { pdf.setPage(i); pdf.setFontSize(8); pdf.setTextColor(110); pdf.text(`AURA | Agency review | ${i} / ${pages}`, 60, 815); }
  pdf.save("aura-first-choice-seo-review.pdf");
}

function OutLink({ href, children }) {
  const safe = deliveryLink(href);
  return safe ? <a href={safe} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs text-primary hover:text-white">{children}<ExternalLink className="h-3 w-3" /></a> : null;
}

function DeliveryEvidence({ data, section }) {
  return <>
    {section === "Intake" && <section className={`${card} p-6 sm:p-7`}><p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">The client brief</p><h2 className="mt-3 text-xl font-medium">{data.client}</h2><p className="mt-4 text-sm leading-7 text-slate-300">{data.brief.goal}</p><dl className="mt-5 space-y-4 text-xs"><div><dt className="text-muted-foreground">Audience</dt><dd className="mt-1.5 text-slate-200">{data.brief.audience}</dd></div><div><dt className="text-muted-foreground">Services</dt><dd className="mt-1.5 leading-6 text-slate-200">{data.brief.services.join(" · ")}</dd></div><div><dt className="text-muted-foreground">Service areas</dt><dd className="mt-1.5 leading-6 text-slate-200">{data.brief.areas.join(" · ")}</dd></div></dl><details className="mt-6 border-t border-white/10 pt-4 text-xs"><summary className="cursor-pointer text-primary">Intake questionnaire & unsent welcome email</summary><div className="mt-4 space-y-4 leading-6 text-slate-300"><ol className="list-inside list-decimal">{data.intake.questions.map((q) => <li key={q}>{q}</li>)}</ol><div className="whitespace-pre-wrap rounded-xl bg-black/20 p-4">{data.intake.email}</div></div></details></section>}
      {section === "Keyword evidence" && <section className="space-y-5"><div className={`${card} p-6`}><p className="text-[10px] uppercase tracking-wider text-primary">Primary article keyword</p><h2 className="mt-3 text-2xl font-semibold">{data.keywords.primary}</h2><p className="mt-3 max-w-3xl text-sm leading-7 text-slate-300">{data.keywords.reason}</p><div className="mt-5 flex flex-wrap gap-x-7 gap-y-2 text-[11px] text-muted-foreground"><span>{data.keywords.source}</span><span>{data.keywords.targeting}</span><span>Retrieved {data.keywords.retrievedAt}</span></div></div><div className={`${card} overflow-x-auto`}><table className="w-full text-left text-xs"><thead className="border-b border-white/10 text-[10px] uppercase tracking-wider text-muted-foreground"><tr>{["Keyword", "Monthly searches", "Ads competition", "Ads index", "Low bid · micros", "High bid · micros", "Intent / use"].map((label) => <th className="px-5 py-4 font-medium" key={label}>{label}</th>)}</tr></thead><tbody className="divide-y divide-white/[0.05]">{data.keywords.rows.map((row) => <tr key={row.keyword} className={row.keyword === data.keywords.primary ? "bg-primary/[0.07]" : ""}><td className="px-5 py-3.5 font-medium text-slate-200">{row.keyword}</td><td className="px-5 py-3.5 text-slate-300">{row.volume.toLocaleString()}</td><td className="px-5 py-3.5 text-muted-foreground">{row.competition}</td><td className="px-5 py-3.5 text-muted-foreground">{row.index}</td><td className="px-5 py-3.5 text-muted-foreground">{row.bidLowMicros == null ? "—" : row.bidLowMicros.toLocaleString()}</td><td className="px-5 py-3.5 text-muted-foreground">{row.bidHighMicros == null ? "—" : row.bidHighMicros.toLocaleString()}</td><td className="px-5 py-3.5 text-muted-foreground">{row.intent}</td></tr>)}</tbody></table></div><div className="grid gap-5 md:grid-cols-2"><section className={`${card} p-6`}><h3 className="text-sm font-medium">How to read these numbers</h3><ul className="mt-4 list-disc space-y-3 pl-4 text-xs leading-6 text-muted-foreground">{data.keywords.notes.map((note) => <li key={note}>{note}</li>)}</ul></section><section className={`${card} p-6`}><h3 className="text-sm font-medium">Ubersuggest supporting suggestions</h3><p className="mt-3 text-xs leading-6 text-muted-foreground">{data.keywords.support.scope}</p><div className="mt-4 flex flex-wrap gap-2">{data.keywords.support.suggestions.map((item) => <span key={item} className="rounded-lg border border-white/10 px-3 py-2 text-[11px] text-slate-300">{item}</span>)}</div><p className="mt-4 text-[11px] leading-6 text-muted-foreground">{data.keywords.support.reuse}</p></section></div></section>}
      {section === "SEO & checks" && <section className="space-y-5"><div className="grid gap-4 lg:grid-cols-3">{data.articles.map((item) => <section className={`${card} p-6`} key={item.location}><div className="flex items-center justify-between"><h2 className="font-medium">{item.location}</h2><CheckCircle2 className="h-4 w-4 text-emerald-300" /></div><p className="mt-2 text-[10px] uppercase tracking-wider text-emerald-300">Saved & independently read back</p><dl className="mt-5 space-y-5 text-xs"><div><dt className="text-muted-foreground">SEO title</dt><dd className="mt-2 leading-6 text-slate-200">{item.seo.title}</dd></div><div><dt className="text-muted-foreground">Meta description</dt><dd className="mt-2 leading-6 text-slate-300">{item.seo.description}</dd></div><div><dt className="text-muted-foreground">Focus keyword</dt><dd className="mt-2 text-primary">{item.seo.focusKeyword}</dd></div></dl><p className="mt-6 border-t border-white/10 pt-4 text-[10px] leading-5 text-muted-foreground">Verified in the RankMath editor · {stamp(item.seo.verifiedAt)}</p></section>)}</div><section className={`${card} p-6`}><h2 className="text-base font-medium">On-page review</h2><ul className="mt-4 grid gap-3 md:grid-cols-2">{data.onPage.map((finding) => <li key={finding} className="flex items-start gap-2.5 text-xs leading-6 text-muted-foreground"><Check className="mt-1.5 h-3 w-3 shrink-0 text-primary" />{finding}</li>)}</ul></section><div className="grid gap-5 lg:grid-cols-2"><section className={`${card} p-6`}><h2 className="text-base font-medium">Imagify image checks</h2><p className="mt-3 text-sm leading-7 text-amber-100/90">{data.images.outcome}</p><p className="mt-3 text-xs leading-6 text-muted-foreground">{data.images.detail}</p><p className="mt-4 rounded-xl bg-black/20 p-4 text-xs leading-6 text-slate-300">{data.images.statistics}</p><p className="mt-4 text-[10px] text-muted-foreground">Inspected {stamp(data.images.checkedAt)}</p></section><section className={`${card} p-6`}><h2 className="text-base font-medium">Exact-site measurements</h2><div className="mt-4 divide-y divide-white/10">{data.measurements.map((item) => <div key={item.label} className="py-3"><div className="flex justify-between text-xs"><span className="text-slate-200">{item.label}</span><span className="text-muted-foreground">{item.status}</span></div><p className="mt-2 text-[11px] leading-5 text-muted-foreground">{item.detail}</p></div>)}</div></section></div></section>}
      {section === "Handoff" && <section className="space-y-5"><section className={`${card} p-6 sm:p-8`}><p className="text-[10px] uppercase tracking-wider text-emerald-300">Verified agency handoff</p><h2 className="mt-3 text-xl font-medium">{data.handoff.title}</h2><p className="mt-4 max-w-3xl text-sm leading-7 text-slate-300">{data.handoff.summary}</p><div className="mt-5"><OutLink href={data.handoff.link}>Open existing Jira handoff</OutLink></div></section><div className="grid gap-4 md:grid-cols-2">{Object.entries(data.execution).map(([label, items]) => <section key={label} className={`${card} p-6`}><h3 className="text-sm font-medium capitalize">{label}</h3><ul className="mt-4 list-disc space-y-3 pl-4 text-xs leading-6 text-muted-foreground">{items.map((item) => <li key={item}>{item}</li>)}</ul></section>)}</div><section className="rounded-2xl border border-primary/20 bg-primary/[0.045] p-6 sm:p-8"><p className="text-[10px] uppercase tracking-wider text-primary">For First Choice SEO</p><h2 className="mt-3 text-xl font-medium">Where would AURA help your team most?</h2><ol className="mt-5 list-decimal space-y-4 pl-5 text-sm leading-7 text-slate-300">{data.feedback.map((question) => <li key={question}>{question}</li>)}</ol></section></section>}
  </>;
}

function DeliveryView({ data, onSave, onSourceSave = null, saving, error }) {
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const stages = [["Intake", "Brief completed"], ["Research", `${data.keywords.rows.length} real ideas`], ["Content", `${data.articles.length} drafts verified`], ["On-page SEO", "Saved fields verified"], ["Image checks", "Checked · see limitation"], ["Handoff", "Task verified"]];
  const supporting = [
    { section: "Intake", tool: "Google Docs", title: "Client brief, questionnaire and welcome email", detail: "Completed intake · Email remains unsent" },
    { section: "Keyword evidence", tool: "Google Ads · Ubersuggest", title: `${data.keywords.rows.length} keyword ideas researched`, detail: "Search volumes, targeting and keyword clusters" },
    { section: "SEO & checks", tool: "RankMath · Imagify", title: "SEO metadata verified and image checks recorded", detail: `${data.articles.length * 3} saved fields · Image optimization not executed` },
    { section: "Handoff", tool: "Jira", title: data.handoff.title, detail: "Existing task updated and read back" },
  ];
  return <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 md:py-12">
    {(error || downloadError) && <p role="alert" className="mb-5 rounded-xl border border-amber-300/30 bg-amber-300/5 p-4 text-sm text-amber-200">{error || downloadError}</p>}
    {onSave && <p className="mb-6 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-violet-200">Review the complete evidence before saving this pack. Articles remain unpublished.</p>}
    <ResultsHeading heading="h1" title={data.title} summary={`${data.articles.length} location articles saved as unpublished drafts, with keyword research, verified SEO metadata and the agency handoff.`} eyebrow={`${data.agency || "Agency"} · workflow results`} />
    <ResultsMetrics metrics={deliveryMetrics(data)} />
    <PrimaryResult title="SEO content package" provider="WordPress" providerVerb="Saved as unpublished drafts in" footer={<span className="flex items-center gap-2 text-emerald-400"><ShieldCheck className="h-3.5 w-3.5" />Fictional client · Articles unpublished · Messages unsent</span>}>
      <ArticleResultPreview articles={data.articles} />
    </PrimaryResult>
    <div className="mb-6 flex items-start gap-2.5 rounded-xl border border-amber-400/15 bg-amber-400/5 px-4 py-3 text-xs leading-5 text-muted-foreground">
      <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
      <p><strong className="font-medium text-amber-200">Image optimization not executed.</strong> {data.images.limitation}</p>
    </div>
    <section aria-label="Results from other apps" className="mb-6">
      <h2 className="mb-3 text-sm font-semibold">Results from other apps</h2>
      <div className="space-y-3">{supporting.map((item) => <div key={item.section} className={`${card} overflow-hidden`}><details className="group">
        <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
          <span className="min-w-0"><span className="block text-[10px] font-semibold text-primary">{item.tool}</span><span className="mt-1 block text-sm font-medium">{item.title}</span><span className="mt-1 block text-[11px] text-muted-foreground">{item.detail}</span></span>
          <span className="inline-flex items-center gap-2 rounded-lg border border-primary/25 px-3 py-1.5 text-xs text-primary">View in AURA<ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" /></span>
        </summary>
        <div className="space-y-4 border-t border-white/10 p-4 sm:p-5"><DeliveryEvidence data={data} section={item.section} /></div>
      </details>{deliveryToolLinks(data, item.section).length > 0 && <div className="flex flex-wrap gap-x-5 gap-y-3 border-t border-white/5 px-5 py-3">{deliveryToolLinks(data, item.section).map((link) => <OutLink href={link.url} key={link.label}>{link.label}</OutLink>)}</div>}</div>)}</div>
    </section>
    <details className="group overflow-hidden rounded-2xl border border-white/10 bg-card/40">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-xs font-medium [&::-webkit-details-marker]:hidden"><span className="flex items-center gap-2"><Activity className="h-4 w-4 text-primary" />Workflow activity</span><ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-180" /></summary>
      <ol className="grid gap-4 border-t border-white/10 p-5 sm:grid-cols-3">{stages.map(([title, detail], index) => <li key={title} className="flex items-start gap-2.5">{index === 4 ? <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" /> : <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />}<span className="text-xs"><span className="font-medium">{title}</span><span className="mt-1 block text-[11px] text-muted-foreground">{detail}</span></span></li>)}</ol>
    </details>
    <div className="mt-5 flex flex-wrap items-center justify-between gap-4 border-t border-white/10 pt-5 text-xs text-muted-foreground">
      <span>Prepared in AURA · {stamp(data.preparedAt)}</span>
      {onSave ? <button type="button" onClick={onSave} disabled={saving} className="rounded-xl bg-primary px-4 py-2.5 font-semibold text-white disabled:opacity-50">{saving ? "Saving review pack…" : "Save review pack"}</button> : <button type="button" disabled={downloading} onClick={async () => { setDownloading(true); setDownloadError(""); try { await downloadReview(data); } catch { setDownloadError("The download couldn't finish. Please try again."); } finally { setDownloading(false); } }} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 hover:bg-white/5 disabled:opacity-50">{downloading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}Download review</button>}
    </div>
    {onSourceSave && <DeliverySourceLinks values={data.sourceLinks} onSave={onSourceSave} />}
  </main>;
}

export default function DeliveryResults() {
  const { deliveryId } = useParams();
  const navigate = useNavigate();
  const input = useRef(null);
  const [data, setData] = useState(null);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(deliveryId !== "new");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const creating = deliveryId === "new";
  useEffect(() => {
    let current = true; setData(null); setError(""); setLoading(!creating);
    const request = creating ? Promise.resolve(null) : deliveryId ? aura.entities.Delivery.get(deliveryId) : aura.entities.Delivery.list("-created_date", 50);
    request.then((value) => { if (!current) return; if (Array.isArray(value)) setRecords(value); else if (value) setData(parseResults(JSON.stringify(value))); }).catch(() => { if (current) setError("These results are unavailable in this workspace. Open Results to choose an accessible review pack."); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [deliveryId, creating]);
  const save = async () => { if (!data || saving) return; setSaving(true); setError(""); try { const saved = await aura.entities.Delivery.create(data); navigate(`/results/${saved.id}`, { replace: true }); } catch { setError("The review pack couldn't be saved yet. Your preview is intact. Please try again."); } finally { setSaving(false); } };
  const saveSources = async (sourceLinks) => {
    await aura.entities.Delivery.update(deliveryId, { sourceLinks });
    const saved = await aura.entities.Delivery.get(deliveryId);
    const verified = parseDeliveryBundle(JSON.stringify(saved));
    if (JSON.stringify(verified.sourceLinks) !== JSON.stringify(sourceLinks)) throw new Error("Links not yet verified");
    setData(verified);
  };
  return <WorkspaceShell
    onBack={() => navigate(deliveryId ? "/results" : "/")}
    backLabel={deliveryId ? "Results" : "Back"}
    onHistoryOpen={() => navigate("/", { state: { openHistory: true } })}
  >
    {loading ? <main className="grid flex-1 place-items-center px-4 py-16" aria-live="polite"><div className="text-center"><Loader2 className="mx-auto h-6 w-6 animate-spin text-primary" /><p className="mt-4 text-sm text-muted-foreground">Opening your verified results…</p></div></main> : data ? data.kind === "marketing_tools" ? <MarketingDeliveryView data={data} /> : data.kind === "campaign_launch" ? <CampaignDeliveryView data={data} onSave={creating ? save : null} saving={saving} error={error} /> : <DeliveryView data={data} onSave={creating ? save : null} onSourceSave={creating ? null : saveSources} saving={saving} error={error} /> : <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 md:py-12"><div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs uppercase tracking-[0.2em] text-primary">AURA</p><h1 className="mt-3 text-3xl font-semibold">{creating ? "Prepare a review pack" : "Workflow results"}</h1></div>{!creating && <Link to="/results/new" className="rounded-xl bg-primary px-4 py-3 text-xs font-semibold">Prepare results</Link>}</div>{error && <p role="alert" className="mt-5 text-sm text-amber-200">{error}</p>}{creating ? <section className={`${card} mt-8 p-8`}><Upload className="h-7 w-7 text-primary" /><h2 className="mt-5 text-lg font-medium">Bring the verified outputs together</h2><p className="mt-3 max-w-xl text-sm leading-7 text-muted-foreground">Choose an AURA results file containing the completed brief, draft content, app outputs and implementation handoff. You’ll review everything before saving.</p><input ref={input} type="file" accept=".json,application/json" className="hidden" aria-label="Verified results file" onChange={async (event) => { setError(""); try { const file = event.target.files?.[0]; if (file) setData(parseResults(await file.text())); } catch (problem) { setError(problem.message); } event.target.value = ""; }} /><button onClick={() => input.current?.click()} className="mt-6 rounded-xl bg-primary px-5 py-3 text-sm font-medium">Choose verified results</button></section> : <div className="mt-8 space-y-3">{records.map((record) => <Link key={record.id} to={`/results/${record.id}`} className={`${card} flex items-center justify-between gap-4 p-6 hover:border-primary/30`}><span><span className="text-[10px] uppercase tracking-wider text-primary">{record.agency || "Agency review"}</span><span className="mt-2 block text-lg font-medium">{record.title}</span><span className="mt-2 block text-xs text-muted-foreground">{record.client} · {stamp(record.preparedAt)}</span></span><ArrowRight className="h-5 w-5 text-primary" /></Link>)}{!records.length && <p className="text-sm text-muted-foreground">Your completed review packs will appear here.</p>}</div>}</main>}
  </WorkspaceShell>;
}
