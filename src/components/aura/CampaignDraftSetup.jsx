import { useEffect, useState } from 'react';
import { ArrowLeft, Mail } from 'lucide-react';
import { getAllConnections, subscribeConnections } from '@/lib/connectionsStore';
import { campaignDraftRequest } from '@/lib/campaignDrafts.mjs';

function Field({ name, label, value, onChange, maxLength, multiline = false, type = 'text' }) {
  const props = { name, value: value || '', required: true, maxLength, onChange: (event) => onChange(name, event.target.value),
    className: 'mt-1.5 w-full rounded-xl border border-white/15 bg-background px-3 py-2.5 text-sm text-foreground' };
  return <label className="block text-sm text-muted-foreground">{label}
    {multiline ? <textarea {...props} rows={5} /> : <input {...props} type={type} />}
  </label>;
}

export default function CampaignDraftSetup({ onSubmit, onBack }) {
  const [values, setValues] = useState({ create_graphic: false });
  const [connections, setConnections] = useState(getAllConnections);
  const [error, setError] = useState('');
  useEffect(() => subscribeConnections(setConnections), []);
  const update = (name, value) => setValues((previous) => ({ ...previous, [name]: value }));
  const submit = (event) => {
    event.preventDefault(); setError('');
    try {
      const request = campaignDraftRequest(values);
      onSubmit(request.prompt, request.tools, request.resources);
    } catch (cause) { setError(cause.message); }
  };
  return <form onSubmit={submit} className="mx-auto w-full max-w-3xl space-y-6 pb-8">
    <button type="button" onClick={onBack} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" />Back to tasks</button>
    <header><p className="text-xs font-semibold uppercase tracking-widest text-primary">Work in your tools</p>
      <h1 className="mt-2 text-2xl font-semibold">Prepare a campaign draft</h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">Save a complete unsent email in the client’s existing Mailchimp account, with an optional editable Canva graphic. Review the exact copy before each write.</p>
    </header>
    <p className="text-sm leading-6 text-muted-foreground">Use this workflow for a Mailchimp client. Other email and ad platforms need their own supported draft actions. No account metrics, client scope or offers are inferred.</p>
    <section className="space-y-4 rounded-2xl border border-white/10 bg-card/60 p-5">
      <h2 className="font-semibold">Client and audience</h2>
      <p className="text-xs leading-5 text-muted-foreground">Mailchimp connection: {connections.Mailchimp ? 'present; capabilities checked when planning' : 'not confirmed; use the Connect menu to connect Mailchimp'}. AURA checks the audience ID and name before creating anything.</p>
      <Field name="client" label="Client name" value={values.client} onChange={update} maxLength={100} />
      <Field name="brief_reference" label="Source for approved copy and offer facts" value={values.brief_reference} onChange={update} maxLength={500} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field name="audience_id" label="Exact Mailchimp audience ID" value={values.audience_id} onChange={update} maxLength={80} />
        <Field name="audience_name" label="Exact Mailchimp audience name" value={values.audience_name} onChange={update} maxLength={200} />
      </div>
      <p className="text-xs leading-5 text-muted-foreground">The draft uses this audience. Recipient eligibility, segmentation and consent must be reviewed before any later send.</p>
    </section>
    <section className="space-y-4 rounded-2xl border border-white/10 bg-card/60 p-5">
      <h2 className="font-semibold">Email content</h2>
      <Field name="title" label="Internal campaign title" value={values.title} onChange={update} maxLength={120} />
      <Field name="subject" label="Subject" value={values.subject} onChange={update} maxLength={150} />
      <Field name="preview_text" label="Preview text" value={values.preview_text} onChange={update} maxLength={150} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field name="from_name" label="Sender name" value={values.from_name} onChange={update} maxLength={100} />
        <Field name="reply_to" label="Reply email address" value={values.reply_to} onChange={update} maxLength={254} type="email" />
      </div>
      <Field name="headline" label="Email headline" value={values.headline} onChange={update} maxLength={90} />
      <Field name="body" label="Approved email body" value={values.body} onChange={update} maxLength={4000} multiline />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field name="cta_label" label="Button text" value={values.cta_label} onChange={update} maxLength={90} />
        <Field name="cta_url" label="Approved destination URL" value={values.cta_url} onChange={update} maxLength={2000} type="url" />
      </div>
      <p className="text-xs leading-5 text-muted-foreground">AURA creates HTML and plain-text versions using the supplied copy, plus Mailchimp’s address and unsubscribe fields. Check their rendered values in Mailchimp before any later send.</p>
    </section>
    <section className="space-y-4 rounded-2xl border border-white/10 bg-card/60 p-5">
      <label className="flex items-center gap-3 text-sm font-medium"><input type="checkbox" checked={values.create_graphic} onChange={(event) => update('create_graphic', event.target.checked)} />Also create an editable Canva graphic</label>
      {values.create_graphic && <><p className="text-xs leading-5 text-muted-foreground">Uses the client name, headline, line below and button text. The graphic is a separate draft for review; it is not posted or embedded in the email.</p>
        <Field name="graphic_line" label="Approved graphic line" value={values.graphic_line} onChange={update} maxLength={90} />
        <p className="text-xs text-muted-foreground">Canva connection: {connections.Canva ? 'present; capabilities checked when planning' : 'not confirmed'}.</p></>}
    </section>
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
    <div className="flex flex-wrap items-center justify-between gap-4">
      <p className="max-w-md text-xs leading-5 text-muted-foreground">Creating a plan makes no external changes. Each saved draft requires review. This workflow has no send, schedule, live-ad or budget action.</p>
      <button type="submit" className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white"><Mail className="h-4 w-4" />Review campaign plan</button>
    </div>
  </form>;
}
