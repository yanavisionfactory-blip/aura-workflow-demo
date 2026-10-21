export const CAMPAIGN_DRAFT_PREFIX = 'AURA_CAMPAIGN_DRAFT_V1\n';

const limits = { client: 100, brief_reference: 500, audience_id: 80, audience_name: 200,
  title: 120, subject: 150, preview_text: 150, from_name: 100, reply_to: 254,
  headline: 90, body: 4000, cta_label: 90, cta_url: 2000 };

export function campaignDraftRequest(input) {
  const values = {};
  for (const [key, limit] of Object.entries(limits)) {
    const value = typeof input[key] === 'string' ? input[key].trim() : '';
    if (!value || [...value].length > limit || /\{\{|\}\}/.test(value)) {
      throw new Error(`Complete ${key.replaceAll('_', ' ')} with literal text of at most ${limit} characters.`);
    }
    values[key] = value;
  }
  if (!/^[A-Za-z0-9_-]{1,80}$/.test(values.audience_id)) throw new Error('Use the exact Mailchimp audience ID.');
  if (!/^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/.test(values.reply_to)) throw new Error('Enter the client reply email address.');
  let url;
  try { url = new URL(values.cta_url); } catch { throw new Error('Enter the approved HTTPS destination.'); }
  if (url.protocol !== 'https:' || url.username || url.password || /\s/.test(values.cta_url)) throw new Error('Use an HTTPS destination without credentials or whitespace.');
  values.create_graphic = input.create_graphic === true;
  if (values.create_graphic) {
    const line = typeof input.graphic_line === 'string' ? input.graphic_line.trim() : '';
    if (!line || [...line].length > 90 || /\{\{|\}\}/.test(line)) throw new Error('Provide a literal Canva graphic line of at most 90 characters.');
    values.graphic_line = line;
  }
  const tools = ['Mailchimp', ...(values.create_graphic ? ['Canva'] : [])];
  return { prompt: CAMPAIGN_DRAFT_PREFIX + JSON.stringify(values), tools,
    resources: { tools, documents: [] } };
}

const verified = (output) => output?.critic?.action === 'accept' && output?.outcome_check?.status === 'verified';

// A create receipt by itself cannot establish that the email body was saved.
export function savedCampaignDraft(outputs = [], primaryKey = null) {
  const saves = outputs.filter((output) => output?.operation === 'mailchimp.campaign.content.set'
    && verified(output) && (!primaryKey || output.step_key === primaryKey));
  for (const saved of [...saves].reverse()) {
    const args = saved.resolved_arguments || {};
    const created = outputs.find((output) => output?.operation === 'mailchimp.campaign.draft.create'
      && verified(output) && output.provider_result?.id === args.campaign_id
      && output.provider_result?.status === 'save'
      && output.resolved_arguments?.audience_id === args.expected_list_id);
    if (!created || !args.html || !args.plain_text) continue;
    if (outputs.some((output) => output?.operation === 'mailchimp.campaign.send'
      && output.resolved_arguments?.campaign_id === args.campaign_id)) continue;
    const fields = created.resolved_arguments;
    return { kind: 'campaign_draft', title: fields.title, provider: 'Mailchimp', providerVerb: 'Saved in',
      completionTitle: 'Unsent campaign saved in Mailchimp',
      completionSummary: 'Campaign settings, full content, audience and unsent status were verified with provider reads.',
      campaignId: args.campaign_id, audienceId: args.expected_list_id, audienceName: fields.audience_name,
      subject: fields.subject, previewText: fields.preview_text, fromName: fields.from_name,
      replyTo: fields.reply_to, body: args.plain_text, link: null, downloadUrl: null };
  }
  return null;
}
