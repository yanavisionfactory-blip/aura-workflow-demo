export const originalPrompt = `Prepare an SEO audit review package for one Mantas Auk client.

Tools publicly named as audit inputs:

- Semrush: keyword, competitor, ranking and backlink research.
- Ahrefs: competitor search visibility and backlink analysis.
- Screaming Frog: website crawling and technical SEO checks.
- Sitebulb: website crawling and technical audit findings.
- Reporting and task-management destinations: confirm their names.

Use supplied exports or verified connections. Confirm the client website, business goals and export dates.

Normalize URLs, combine overlapping findings and preserve source evidence. Group issues into technical SEO, content, internal linking and backlinks.

Deliver a prioritized roadmap and implementation backlog with affected URLs, evidence, proposed fixes, effort, dependencies and reasoning. Flag contradictions and checks requiring expert review. Do not modify the website.`;

export const interpretation = 'Prepare one SEO audit review from supplied crawl evidence and clearly labelled research examples. Keep URL-level evidence, prioritise implementation work and show missing confirmations. Make no external changes.';

const step = (tool, title, action, output) => ({ tool, title, action, output, iWill: action[0].toLowerCase() + action.slice(1), riskLevel: 'read', flow: [{ label: 'Uses', value: tool }] });
export const workflowSteps = [
  step('Screaming Frog', 'Inspect the supplied crawl', 'Analyse the anonymized Screaming Frog export', '171 URL records; source rows, duplicate-file warning and crawl date retained.'),
  step('Semrush', 'Review search demand', 'Review simulated keyword and competitor research', 'Illustrative rankings and demand mapped to real page paths; no live provider request.'),
  step('Ahrefs', 'Review visibility and backlinks', 'Review simulated visibility and backlink evidence', 'Sample visibility trends and fictional referring domains, all labelled.'),
  step('Sitebulb', 'Compare technical findings', 'Inspect the simulated Sitebulb audit', 'Derived crawl counts distinguished from hypothetical orphan and language checks.'),
  step('AURA Intelligence', 'Prepare the review package', 'Combine evidence into a roadmap and backlog', '10 proposed items, URL scopes, fixes, effort, dependencies and expert review checks. No document, ticket or website write.'),
];

export const tour = [
  { phase: 'input', title: 'Describe the outcome', caption: 'AURA starts with one task in its normal command interface. This example preserves the original SEO request.', seconds: 7 },
  { phase: 'plan', title: 'Inspect the plan', caption: 'The plan keeps the real crawl export and each simulated research source distinct.', seconds: 9 },
  { phase: 'review', title: 'Review before running', caption: 'Check source status, dates, missing confirmations and proposed outputs. Approval starts only the local demo.', seconds: 10 },
  { phase: 'execution', title: 'Follow the work', caption: 'This is prepared playback through the native execution interface. No provider calls or external changes occur.', seconds: 12 },
  { phase: 'results', title: 'Open the final result', caption: 'One result displays what happened, tools used and the proposed implementation roadmap.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Tool activity', tool: 'crawl' }, title: 'Inspect Screaming Frog', caption: '171 real URL records support 82 observed canonical conflicts. The client hostname is anonymized.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Tool activity', tool: 'semrush' }, title: 'Inspect Semrush', caption: 'The keyword and competitor tables are simulated examples, with real page paths and explicit labels.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Tool activity', tool: 'ahrefs' }, title: 'Inspect Ahrefs', caption: 'Visibility and backlink examples use fictional referring domains. These are not vendor receipts.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Tool activity', tool: 'sitebulb' }, title: 'Inspect Sitebulb', caption: 'Derived crawl counts do not independently confirm Screaming Frog. Orphan and hreflang checks remain hypothetical.', seconds: 8 },
  { phase: 'results', focus: { tab: 'Backlog', group: '', priority: 'P1', issue: 'T01' }, title: 'Turn evidence into a roadmap', caption: 'The first priority includes affected URLs, the proposed fix, effort, dependencies, reasoning and an acceptance check.', seconds: 10 },
  { phase: 'results', focus: { tab: 'Sources & intake' }, title: 'Keep evidence limits visible', caption: 'Dates, duplicated exports, unknown crawl settings and unconfirmed client goals remain visible. Google Docs and Jira are destination examples only.', seconds: 10 },
  { phase: 'feedback', title: 'Ask for candid feedback', caption: 'A practitioner can describe the value, missing safeguards and conditions for a real evaluation in their own words.', seconds: 8 },
];

export const validPhases = new Set(['input', 'plan', 'review', 'execution', 'results', 'feedback']);
export function executionSteps(completed) {
  return workflowSteps.map((item, index) => ({ ...item, status: index < completed ? 'completed' : index === completed ? 'running' : 'pending', liveOutput: index < completed ? item.output : '' }));
}
