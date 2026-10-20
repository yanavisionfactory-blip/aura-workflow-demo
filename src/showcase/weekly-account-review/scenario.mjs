export const originalPrompt = `Prepare a weekly account review for one SmartSites client.

Tools publicly named in their services:

- Google Ads, Meta Ads, Microsoft Advertising and Amazon Ads: paid advertising.
- Klaviyo: email/SMS campaigns, segmentation and customer journeys.
- Mailchimp: email campaigns and automations.
- HubSpot: marketing automation.
- Client reporting destination: confirm the selected account’s setup.

Use only the platforms included in this client’s scope. Work from approved exports or verified connections, the client’s goals and brand brief.

Align reporting periods and metric definitions. Identify significant performance changes and propose three evidence-supported tests. Draft relevant ad or email variants.

Deliver a checked summary, proposed experiments and implementation backlog. Keep attributed results separate where definitions differ. Do not launch campaigns, change budgets or send messages.`;

const step = (tool, title, action, output) => ({ tool, title, action, output, iWill: action[0].toLowerCase() + action.slice(1), riskLevel: 'read', flow: [{ label: 'Uses', value: tool }] });
export const workflowSteps = [
  step('AURA Intelligence', 'Check the scoped inputs', 'Check the fictional client brief, platform scope and reporting destination', 'Three sample inputs in scope; four named platforms and SMS excluded. Real client and Client Hub confirmation remain open.'),
  step('Google Ads', 'Review paid search', 'Inspect simulated Google Ads campaign and search-term rows', 'Two aligned weeks, source row references, non-brand CPA and query-mix changes.'),
  step('Meta Ads', 'Review paid social', 'Inspect simulated Meta ad-set performance', 'Separate attribution, link clicks, purchase credits and row-level reach/frequency.'),
  step('Klaviyo', 'Review lifecycle email', 'Inspect simulated campaign segments and flow message cohorts', 'Message click rates, audience-mix change, consent and attribution caveats. SMS is not in scope.'),
  step('AURA Intelligence', 'Reconcile periods and metrics', 'Recalculate ratios and preserve different attribution definitions', 'Material changes flagged descriptively; no blended ROAS, cross-platform order total or causal winner.'),
  step('AURA Intelligence', 'Prepare the review package', 'Prepare the checked summary, three tests, creative drafts and backlog', 'Three proposed experiments, six draft variants and eight implementation items. No external changes or messages.'),
];

export const tour = [
  { phase: 'input', title: 'Start with the weekly-review task', caption: 'The original brief is preserved. This prepared example uses a fictional client and simulated data.', seconds: 7 },
  { phase: 'plan', title: 'Inspect the scoped plan', caption: 'Only Google Ads, Meta Ads and Klaviyo email are in this scenario. Four other named platforms and SMS are explicitly excluded.', seconds: 8 },
  { phase: 'review', title: 'Review before running', caption: 'Check the complete weeks, currency, timezone, attribution definitions and proposed outputs. Approval starts local demo playback only.', seconds: 10 },
  { phase: 'execution', title: 'Follow the prepared review', caption: 'The native execution view plays through six read-only stages. No provider calls, launches, budget changes or message sends occur.', seconds: 14 },
  { phase: 'results', title: 'See one final review', caption: 'The result combines a checked summary, individual platform outputs, three tests, draft variants and an implementation backlog.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Tool activity', source: 'google' }, title: 'Inspect the Google Ads rows', caption: 'Non-brand CPA rose from $25 to $50 in the sample. Search terms are a breakdown of the campaign, so they are not added to the totals again.', seconds: 10 },
  { phase: 'results', focus: { tab: 'Experiments', experiment: 'E1' }, title: 'Review the Search test proposal', caption: 'The proposed message test keeps targeting, landing page and budget fixed. Evidence, guardrails and sample-size limitations stay visible.', seconds: 10 },
  { phase: 'results', focus: { tab: 'Creative drafts', creative: 'search-message' }, title: 'Compare Search ad drafts', caption: 'Switch between the two draft message bundles. Headline and description lengths are checked; no RSA is uploaded.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Tool activity', source: 'meta' }, title: 'Inspect Meta separately', caption: 'The sample video CPA rose from $25 to $60 as link CTR fell and frequency increased. These observations do not prove creative fatigue.', seconds: 10 },
  { phase: 'results', focus: { tab: 'Experiments', experiment: 'E2' }, title: 'Review the Meta test proposal', caption: 'A randomized creative-concept test is proposed. Repeated impressions cannot be treated as independent users; power and assets need review.', seconds: 10 },
  { phase: 'results', focus: { tab: 'Creative drafts', creative: 'meta-concept' }, title: 'Inspect the social concepts', caption: 'AURA displays draft copy and opening-frame storyboards. These are previews, not live Meta ads or finished videos.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Tool activity', source: 'klaviyo' }, title: 'Inspect Klaviyo cohorts', caption: 'Campaign click rate fell from 2.4% to 1.2%, while audience mix changed. Flow and campaign rows retain their own evidence.', seconds: 10 },
  { phase: 'results', focus: { tab: 'Experiments', experiment: 'E3' }, title: 'Review the email test proposal', caption: 'Randomize the subject line within one engaged segment. Keep the message body fixed and check whether the eligible audience is large enough.', seconds: 10 },
  { phase: 'results', focus: { tab: 'Creative drafts', creative: 'email-subject' }, title: 'Compare email subjects', caption: 'Both variants share the same preheader, body and CTA. Nothing is created in Klaviyo, and no recipient list or send action is set.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Backlog', priority: 'P1', task: 'B02' }, title: 'See the implementation gates', caption: 'Input confirmation, measurement reconciliation and experiment sizing come first. Proposed work includes owners, effort, dependencies and acceptance checks.', seconds: 10 },
  { phase: 'results', focus: { tab: 'Sources & scope' }, title: 'Check scope and reporting limits', caption: 'Client Hub is an agency-supported reporting candidate. This client’s account, URL and permissions remain unconfirmed; platform revenue is never added together.', seconds: 10 },
  { phase: 'feedback', title: 'Collect professional feedback', caption: 'Ask what is useful, what is missing, and what a practitioner would validate before a real client review. Responses stay local.', seconds: 6 },
];
export const validPhases = new Set(['input', 'plan', 'review', 'execution', 'results', 'feedback']);
export function executionSteps(completed) {
  return workflowSteps.map((item, index) => ({ ...item, status: index < completed ? 'completed' : index === completed ? 'running' : 'pending', liveOutput: index < completed ? item.output : '' }));
}
