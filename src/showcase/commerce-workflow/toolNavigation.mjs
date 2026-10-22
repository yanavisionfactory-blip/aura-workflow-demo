import { simulationInputs } from '../../lib/commerceSimulation.mjs';

export const TOOL_PAGES = {
  google: { defaultView: 'ads', pages: [['campaigns', 'Campaigns'], ['search-terms', 'Search terms'], ['ads', 'Ads & assets'], ['experiment', 'Experiment draft'], ['source', 'Source details']] },
  meta: { defaultView: 'creatives', pages: [['performance', 'Ad performance'], ['creatives', 'Creative previews'], ['experiment', 'Creative test'], ['source', 'Source details']] },
  amazon: { defaultView: 'targeting', pages: [['campaigns', 'Campaigns'], ['search-terms', 'Search terms'], ['targeting', 'Targeting draft'], ['product', 'Advertised product'], ['source', 'Source details']] },
  seller: { defaultView: 'listing', pages: [['listing', 'Listing draft'], ['inventory', 'Inventory'], ['business', 'Sales & traffic'], ['source', 'Source details']] },
};
const evidenceRoutes = new Map();
for (const [tool, input] of Object.entries(simulationInputs())) {
  for (const row of input.rows) evidenceRoutes.set(row.id, { tool, view: tool === 'seller' ? 'business' : tool === 'meta' ? 'performance' : row.report === 'search_terms' ? 'search-terms' : 'campaigns' });
  if (input.listing) evidenceRoutes.set(input.listing.id, { tool, view: 'inventory' });
}
export function toolHref(tool, view = TOOL_PAGES[tool]?.defaultView, evidence) {
  if (!Object.hasOwn(TOOL_PAGES, tool)) throw new Error('Unknown demo tool.');
  if (!TOOL_PAGES[tool].pages.some(([key]) => key === view)) throw new Error('Unknown demo tool view.');
  const params = new URLSearchParams({ tool, view });
  if (evidence && evidenceRoutes.get(evidence)?.tool === tool) params.set('evidence', evidence);
  return `?${params}`;
}
export function evidenceHref(id) {
  const route = evidenceRoutes.get(id);
  if (!route) throw new Error('Unknown source evidence.');
  return toolHref(route.tool, route.view, id);
}
export function readToolRoute(search) {
  const params = new URLSearchParams(search), tool = params.get('tool');
  if (!tool || !Object.hasOwn(TOOL_PAGES, tool)) return null;
  const inputView = params.get('view');
  const evidence = params.get('evidence');
  const validEvidence = evidenceRoutes.get(evidence)?.tool === tool ? evidence : undefined;
  const view = validEvidence ? evidenceRoutes.get(evidence).view : TOOL_PAGES[tool].pages.some(([key]) => key === inputView) ? inputView : TOOL_PAGES[tool].defaultView;
  return { tool, view, evidence: validEvidence };
}
