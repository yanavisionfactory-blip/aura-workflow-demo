import { useEffect, useState } from 'react';
import { ArrowLeft, Download, FileBarChart, Loader2 } from 'lucide-react';
import { getAllConnections, subscribeConnections } from '@/lib/connectionsStore';
import { approvedWeeklyRequest, weeklyCsvTemplate, weeklyPeriods, WEEKLY_PLATFORMS } from '@/lib/weeklyReviewIntake.mjs';

const fieldClass = 'mt-1 w-full rounded-lg border border-white/15 bg-background p-2.5 text-sm text-foreground';
function TextField({ label, value, onChange, type = 'text', multiline = false }) {
  const props = { className: fieldClass, value: value || '', onChange: (event) => onChange(event.target.value), required: true };
  return <label className="block text-xs text-muted-foreground">{label}{multiline ? <textarea {...props} rows={3} maxLength={6000}/> : <input {...props} type={type} maxLength={2000}/>}</label>;
}
function downloadTemplate(key) {
  const url = URL.createObjectURL(new Blob([weeklyCsvTemplate(key)], { type: 'text/csv' }));
  const link = document.createElement('a'); link.href = url; link.download = `${key}-weekly-template.csv`; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function WeeklyReviewSetup({ onSubmit, onBack }) {
  const [connections, setConnections] = useState(getAllConnections);
  const [client, setClient] = useState({ name: '', id: '', fictional: false, engagementConfirmed: false });
  const [scope, setScope] = useState({ included: [], confirmed: false, approvalReference: '' });
  const [brief, setBrief] = useState({ goals: '', brand: '', approvalReference: '' });
  const [reporting, setReporting] = useState({ confirmed: false, destination: '', destinationUrl: '', confirmedBy: '', approvalReference: '' });
  const [sourceInputs, setSourceInputs] = useState({});
  const [timezone, setTimezone] = useState('America/Chicago'), [currency, setCurrency] = useState('USD');
  const [cutoff, setCutoff] = useState('');
  const [end, setEnd] = useState(''), [threshold, setThreshold] = useState('20');
  const [error, setError] = useState(''), [reading, setReading] = useState(false);
  useEffect(() => subscribeConnections(setConnections), []);
  const updateSource = (key, field, value) => setSourceInputs((previous) => ({ ...previous, [key]: { ...previous[key], [field]: value } }));
  const readCsv = async (key, file) => {
    if (!file) return;
    setError(''); setReading(true);
    setSourceInputs((previous) => ({ ...previous, [key]: { ...previous[key], csv_text: '', filename: '' } }));
    try {
      if (file.size > 200000) throw new Error('Use an approved, aggregated CSV smaller than 200 KB.');
      const csv_text = await file.text();
      setSourceInputs((previous) => ({ ...previous, [key]: { ...previous[key], csv_text, filename: file.name } }));
    } catch (cause) { setError(cause.message); } finally { setReading(false); }
  };
  const submit = (event) => {
    event.preventDefault(); setError('');
    try {
      const periods = weeklyPeriods(end);
      const today = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
      if (end >= today) throw new Error('Choose a reporting week that ended before today in the client timezone.');
      const config = { version: 2, agency: 'SmartSites', client, scope, brief, reporting,
        currency: currency.toUpperCase(), timezone, periods, asOf: cutoff, materialityThreshold: Number(threshold) / 100,
        expertChecks: ['Descriptive materiality is not statistical significance. Plan power and attribution maturity before a live test.', 'No campaigns, budgets, messages or external reporting destinations are changed.'], references: [] };
      const request = approvedWeeklyRequest(config, sourceInputs);
      onSubmit(request.prompt, [], request.resources);
    } catch (cause) { setError(cause.message); }
  };
  return <form onSubmit={submit} className="mx-auto max-w-3xl space-y-6" aria-label="Weekly account review setup">
    <button type="button" onClick={onBack} className="inline-flex items-center gap-2 text-xs text-muted-foreground"><ArrowLeft className="h-4 w-4"/>Back to tasks</button>
    <div><p className="text-xs text-primary">SmartSites · approved client inputs</p><h1 className="mt-2 text-2xl font-semibold">Prepare a weekly account review</h1><p className="mt-3 text-sm leading-6 text-muted-foreground">Select one client and only its contracted platforms. AURA will check the exports, calculate the comparison and draft three tests, six variants and a backlog for review.</p></div>
    <section className="space-y-4 rounded-2xl border border-white/10 bg-card/50 p-5"><h2 className="font-semibold">Client and reporting period</h2>
      <div className="grid gap-4 sm:grid-cols-2"><TextField label="Client name" value={client.name} onChange={(name) => setClient({ ...client, name })}/><TextField label="Client reference / ID" value={client.id} onChange={(id) => setClient({ ...client, id })}/><TextField label="Last complete day of review week" type="date" value={end} onChange={setEnd}/><TextField label="Client account timezone (IANA)" value={timezone} onChange={setTimezone}/><TextField label="Common export extraction cutoff (ISO timestamp with timezone)" value={cutoff} onChange={setCutoff}/><TextField label="Reporting currency (ISO code)" value={currency} onChange={setCurrency}/><TextField label="Material weekly change threshold (%)" type="number" value={threshold} onChange={setThreshold}/></div>
      {end && <p className="text-xs text-muted-foreground">Compare {weeklyPeriods(end).current.label} with {weeklyPeriods(end).previous.label}. Identical timezone, currency and extraction cutoff are required; attribution definitions remain separate.</p>}
      <label className="flex gap-2 text-xs leading-5"><input type="checkbox" required checked={client.engagementConfirmed} onChange={(event) => setClient({ ...client, engagementConfirmed: event.target.checked })}/>I confirm this is the selected SmartSites client and its engagement is current.</label>
    </section>
    <section className="space-y-4 rounded-2xl border border-white/10 bg-card/50 p-5"><h2 className="font-semibold">Approved scope and sources</h2><p className="text-xs leading-6 text-muted-foreground">A workspace connection does not confirm this client’s account or reporting permissions. Approved exports can be used without connecting an app. Use Connect above for live account setup; this review processes exports and makes no vendor reporting calls. Klaviyo, Mailchimp and HubSpot inputs here cover email campaign and automation message cohorts. SMS requires a separate review.</p>
      <div className="grid gap-2 sm:grid-cols-2">{WEEKLY_PLATFORMS.map((platform) => <label key={platform.key} className="rounded-xl border border-white/10 p-3 text-sm"><span className="flex gap-2"><input type="checkbox" checked={scope.included.includes(platform.key)} onChange={(event) => setScope({ ...scope, included: event.target.checked ? [...scope.included, platform.key] : scope.included.filter((key) => key !== platform.key) })}/>{platform.name}</span><span className="mt-1 block pl-5 text-[11px] text-muted-foreground">{platform.aliases.some((name) => connections[name]) ? 'Workspace connection present · client mapping required' : 'No matching workspace connection · export required'}</span></label>)}</div>
      <TextField label="Scope approval reference" value={scope.approvalReference} onChange={(approvalReference) => setScope({ ...scope, approvalReference })}/>
      <label className="flex gap-2 text-xs"><input type="checkbox" required checked={scope.confirmed} onChange={(event) => setScope({ ...scope, confirmed: event.target.checked })}/>These selected platforms are included in this client’s approved scope.</label>
      {WEEKLY_PLATFORMS.filter((platform) => scope.included.includes(platform.key)).map((platform) => <fieldset key={platform.key} className="space-y-3 rounded-xl border border-primary/20 p-4"><legend className="px-2 text-sm font-semibold">{platform.name}</legend><div className="grid gap-3 sm:grid-cols-2">{[['accountId', 'Selected client account ID'], ['approvedBy', 'Export approved by'], ['approvalReference', 'Export approval reference'], ['dateBasis', 'Date basis (e.g. interaction date or send cohort)'], ['attribution', 'Attribution model, window and filters'], ['clickDefinition', 'Click definition and bot filters (e.g. link clicks or per-message unique clicks)'], ['conversionDefinition', 'Conversion event / outcome definition'], ['revenueDefinition', 'Value definition (or unavailable)']].map(([field, label]) => <TextField key={field} label={label} value={sourceInputs[platform.key]?.[field]} onChange={(value) => updateSource(platform.key, field, value)}/>)}</div><p className="text-xs leading-6 text-muted-foreground">Use weekly campaign or message rows with unique evidence IDs, period current/previous and conversions matching the stated definition. Leave revenue blank when unavailable. Do not combine campaign totals with their breakdowns, or overlapping email segments. Deduplicate upstream. Templates contain no performance values.</p><button type="button" onClick={() => downloadTemplate(platform.key)} className="inline-flex items-center gap-2 text-xs text-primary"><Download className="h-3 w-3"/>Download {platform.name} CSV template</button><label className="block text-xs text-muted-foreground">Approved {platform.name} CSV<input className={fieldClass} type="file" accept=".csv,text/csv" onChange={(event) => readCsv(platform.key, event.target.files?.[0])}/></label><p className="text-xs">{sourceInputs[platform.key]?.filename || 'No export selected'}</p></fieldset>)}
    </section>
    <section className="space-y-4 rounded-2xl border border-white/10 bg-card/50 p-5"><h2 className="font-semibold">Goals and brand brief</h2><TextField label="Client goals, KPI targets and metric definitions" multiline value={brief.goals} onChange={(goals) => setBrief({ ...brief, goals })}/><TextField label="Approved brand facts, tone, claims, offers and exclusions" multiline value={brief.brand} onChange={(brand) => setBrief({ ...brief, brand })}/><TextField label="Goals and brand approval reference" value={brief.approvalReference} onChange={(approvalReference) => setBrief({ ...brief, approvalReference })}/></section>
    <section className="space-y-4 rounded-2xl border border-white/10 bg-card/50 p-5"><h2 className="font-semibold">Client reporting destination</h2><label className="flex gap-2 text-xs leading-5"><input type="checkbox" checked={reporting.confirmed} onChange={(event) => setReporting({ ...reporting, confirmed: event.target.checked })}/>The selected client’s reporting destination and access have been confirmed.</label>{reporting.confirmed ? <div className="grid gap-3 sm:grid-cols-2">{[['destination', 'Destination name'], ['destinationUrl', 'Exact HTTPS destination URL'], ['confirmedBy', 'Confirmed by'], ['approvalReference', 'Setup and access confirmation reference']].map(([field, label]) => <TextField key={field} label={label} value={reporting[field]} onChange={(value) => setReporting({ ...reporting, [field]: value })}/>)}</div> : <p className="text-xs leading-6 text-amber-200">Destination unconfirmed. The draft remains in AURA with a visible handoff blocker. No Client Hub, Google Doc or other destination is assumed.</p>}</section>
    {error && <p role="alert" className="rounded-xl border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-200">{error}</p>}
    <div className="flex flex-wrap items-center justify-between gap-4"><p className="max-w-md text-xs leading-6 text-muted-foreground">Inputs are submitted to your AURA workspace when you create the plan. No campaigns, budget changes, external tasks or messages are included.</p><button type="submit" disabled={reading} className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white disabled:opacity-50">{reading ? <Loader2 className="h-4 w-4 animate-spin"/> : <FileBarChart className="h-4 w-4"/>}Check inputs and create plan</button></div>
  </form>;
}
