export default function CampaignDraftResult({ result }) {
  return <div className="space-y-5">
    <p className="text-sm text-emerald-300">Saved and verified as an unsent Mailchimp draft</p>
    <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
      {[
        ['Campaign ID', result.campaignId], ['Audience', `${result.audienceName} (${result.audienceId})`],
        ['Subject', result.subject], ['Preview text', result.previewText],
        ['Sender', result.fromName], ['Reply address', result.replyTo],
      ].map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words">{value}</dd></div>)}
    </dl>
    <section className="rounded-2xl border border-white/10 bg-background/60 p-5" aria-label="Saved email content">
      <h3 className="mb-3 text-sm font-semibold">Saved email content</h3>
      <p className="whitespace-pre-wrap break-words text-sm leading-7">{result.body}</p>
    </section>
    <p className="text-xs leading-6 text-muted-foreground">The provider readbacks matched the campaign settings, full HTML and plain text, selected audience and unsent status. Review Mailchimp’s rendered email, footer and recipient eligibility before any later send.</p>
    {result.graphic?.link && <a href={result.graphic.link} target="_blank" rel="noopener noreferrer" className="inline-flex rounded-xl border border-primary/30 px-4 py-2 text-sm font-medium text-primary">Open campaign graphic in Canva</a>}
  </div>;
}
