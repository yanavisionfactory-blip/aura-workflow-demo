import sample from '../showcase/website-content/data.mjs';
import { pageHTML } from './websiteContentExport.mjs';
import { websiteCMSPreview } from './websiteCMSPreview.mjs';

export const WEBSITE_SIMULATION_KEY = 'aura.website-simulation.v1';
export const WEBSITE_SIMULATION_STEPS = [
  ['website', 'Read five sample website pages'], ['sitemap', 'Check the sample sitemap'],
  ['brief', 'Apply the sample brand brief'], ['assets', 'Match the sample image manifest'],
  ['systems', 'Confirm the four tool roles separately'], ['content', 'Prepare copy, comparisons and review tracker'],
  ['approval', 'Approve the sample package'], ['wordpress', 'WordPress · create and check five drafts'],
  ['shopify', 'Shopify · create and check five drafts'], ['woocommerce', 'WooCommerce · create and check five WordPress pages'],
  ['bigcommerce', 'BigCommerce · create and check five web pages'], ['handoff', 'Verify the complete developer handoff'],
].map(([key, name]) => ({ key, name }));
const check = (condition, message) => { if (!condition) throw new Error(message); };
const canonical = value => JSON.stringify(value, (_key, item) => item && typeof item === 'object' && !Array.isArray(item) ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
export const websiteSimulationHash = async value => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(value)))), byte => byte.toString(16).padStart(2, '0')).join('');
const clone = value => structuredClone(value);

// Authored test inputs, not a fresh website crawl, client-approved files, or AI generation.
export function websiteSimulationInputs() {
  return {
    mode: 'simulated', client: sample.client, website: sample.website,
    websitePages: sample.pages.map(page => ({ page_id: page.page_id, url: page.url, original: clone(page.original), simulated: true })),
    sitemap: { simulated: true, urls: sample.pages.map(page => page.url) },
    brief: { simulated: true, text: sample.working_brief, reviewer: 'Demo reviewer — simulated role', approvedForSimulation: true },
    assets: sample.pages.flatMap(page => page.assets.map((asset, index) => ({ id: `SIM-${page.page_id}-image-${index + 1}`, page_id: page.page_id, requirement: asset.requirement, alt_text: asset.alt_text, crop: asset.crop, simulated: true, approvedForSimulation: true }))),
    systems: [
      { area: 'CMS', selected: 'WordPress', alternatives: ['Shopify', 'WooCommerce', 'BigCommerce'], simulated: true, actualConnectionVerified: false },
      { area: 'Asset storage', selected: 'AURA sample asset manifest', simulated: true, actualClientTool: 'Unconfirmed' },
      { area: 'Approval', selected: 'AURA demo approval tracker', simulated: true, actualClientTool: 'Unconfirmed' },
      { area: 'Project management', selected: 'AURA demo developer handoff', simulated: true, actualClientTool: 'Unconfirmed' },
    ],
    draftTemplates: clone(sample.pages),
  };
}

async function validateInputs(inputs) {
  check(canonical(inputs) === canonical(websiteSimulationInputs()), 'Use the complete labelled sample inputs. This simulation does not accept real client files or altered scenario copy.');
  check(inputs.websitePages.length === 5 && new Set(inputs.websitePages.map(page => page.url)).size === 5, 'Five unique sample pages are required.');
  check(inputs.websitePages.every(page => inputs.sitemap.urls.includes(page.url)), 'A page is missing from the sample sitemap.');
  check(inputs.brief.approvedForSimulation && inputs.assets.every(asset => asset.approvedForSimulation && asset.simulated), 'The sample brief and asset permissions are incomplete.');
}

async function receipt(key, input, onStep) {
  await onStep({ key, status: 'running' });
  const result = { key, id: crypto.randomUUID(), executed_at: new Date().toISOString(), input_sha256: await websiteSimulationHash(input), mode: 'simulated', provider_api_called: false };
  await onStep({ key, status: 'completed' });
  return result;
}

export async function prepareWebsiteSimulation({ inputs = websiteSimulationInputs(), onStep = () => {} } = {}) {
  await validateInputs(inputs);
  const receipts = [];
  for (const [key, input] of [['website', inputs.websitePages], ['sitemap', inputs.sitemap], ['brief', inputs.brief], ['assets', inputs.assets], ['systems', inputs.systems]]) receipts.push(await receipt(key, input, onStep));
  const packet = clone(sample);
  packet.summary = 'AURA executed the authored five-page sample workflow. All CMS actions and approval decisions in this run are simulated.';
  packet.pages = inputs.draftTemplates.map(template => ({ ...clone(template), original: clone(inputs.websitePages.find(page => page.page_id === template.page_id).original) }));
  const contentHash = await websiteSimulationHash(packet.pages);
  receipts.push(await receipt('content', packet.pages, onStep));
  packet.simulationExecution = {
    schema: 1, id: crypto.randomUUID(), mode: 'browser_executed_website_simulation', status: 'awaiting_demo_approval',
    started_at: new Date().toISOString(), inputs: clone(inputs), input_sha256: await websiteSimulationHash(inputs), content_sha256: contentHash,
    receipts, approval: null, tools: [], simulated_records_created: 0, verified_readbacks: 0,
    provider_api_called: false, model_call_executed: false, external_writes: false, live_pages_modified: false,
    drafting: 'Authored sample copy assembled and checked against the sample sources; no runtime model generation.',
  };
  return packet;
}

export async function approveWebsiteSimulation(packet) {
  await verifyPrepared(packet);
  const approved = clone(packet);
  approved.simulationExecution.approval = { simulated: true, reviewer: 'Demo reviewer — simulated role', status: 'approved_for_simulation_only', content_sha256: await websiteSimulationHash(packet.pages), assets_sha256: await websiteSimulationHash(packet.simulationExecution.inputs.assets), approved_at: new Date().toISOString() };
  return approved;
}

function nativePayload(provider, page) {
  const body = page.body_html, seo = clone(page.seo), images = clone(page.asset_requirements);
  if (provider === 'shopify') return { title: page.title, handle: page.proposed_path.split('/').pop(), body_html: body, published: false, published_at: null, metafields: { title_tag: seo.page_title, description_tag: seo.meta_description }, sample_images: images };
  if (provider === 'bigcommerce') return { name: page.title, type: 'page', body, is_visible: false, url: { path: page.proposed_path }, page_title: seo.page_title, meta_description: seo.meta_description, sample_images: images };
  return { type: 'page', status: 'draft', slug: page.proposed_path.split('/').filter(Boolean).join('-') || 'home', title: { rendered: page.title }, content: { rendered: body }, meta: { sample_page_title: seo.page_title, sample_meta_description: seo.meta_description }, sample_images: images, ...(provider === 'woocommerce' ? { content_owner: 'WordPress' } : {}) };
}
function readNative(provider, record) {
  if (provider === 'shopify') return { title: record.title, body: record.body_html, seo: { page_title: record.metafields.title_tag, meta_description: record.metafields.description_tag }, images: record.sample_images, unpublished: record.published === false && record.published_at === null };
  if (provider === 'bigcommerce') return { title: record.name, body: record.body, seo: { page_title: record.page_title, meta_description: record.meta_description }, images: record.sample_images, unpublished: record.is_visible === false };
  return { title: record.title.rendered, body: record.content.rendered, seo: { page_title: record.meta.sample_page_title, meta_description: record.meta.sample_meta_description }, images: record.sample_images, unpublished: record.status === 'draft' };
}

// Local adapter: no credentials, fetch, vendor SDK, remote resource, or publish operation.
// Each provider gets an isolated test store seeded with protected live-page fixtures.
export function createSimulatedWebsiteAdapter(provider, runId, pages) {
  check(['wordpress', 'shopify', 'woocommerce', 'bigcommerce'].includes(provider), 'Unknown simulated provider.');
  const live = pages.map(page => ({ id: `protected-live-${page.page_id}`, url: page.url, original: clone(page.original), status: 'published' }));
  const drafts = new Map(), operations = [];
  return {
    health: () => ({ simulated: true, available: true, realConnectionVerified: false }),
    liveSnapshot: () => clone(live),
    createDraft(page) {
      const existing = drafts.get(page.page_id);
      if (existing) return clone(existing);
      const record = { id: `SIM-${runId}-${provider}-${page.page_id}`, simulated: true, ...nativePayload(provider, page) };
      drafts.set(page.page_id, record);
      operations.push({ operation: 'create_draft', page_id: page.page_id, record_id: record.id, simulated: true });
      return clone(record);
    },
    readDraft(pageId) {
      check(drafts.has(pageId), 'The simulated draft does not exist.');
      const record = drafts.get(pageId);
      operations.push({ operation: 'read_draft', page_id: pageId, record_id: record.id, simulated: true });
      return clone(record);
    },
    operations: () => clone(operations),
  };
}

async function verifyPrepared(packet) {
  const run = packet?.simulationExecution;
  check(run?.mode === 'browser_executed_website_simulation' && run.schema === 1, 'This is not an executed website simulation.');
  await validateInputs(run.inputs);
  check(run.input_sha256 === await websiteSimulationHash(run.inputs), 'The sample inputs changed.');
  check(canonical(packet.pages) === canonical(run.inputs.draftTemplates) && run.content_sha256 === await websiteSimulationHash(packet.pages), 'The reviewed copy or page version changed.');
  check(run.provider_api_called === false && run.model_call_executed === false && run.external_writes === false && run.live_pages_modified === false, 'The simulation must not claim real provider or model execution.');
  check(canonical(packet.systems) === canonical(sample.systems) && packet.staging.drafts_created === 0 && packet.pages.every(page => page.approval.status === 'pending'), 'Real client tools and approvals must remain unconfirmed.');
  check(run.receipts.length >= 6 && new Set(run.receipts.slice(0, 6).map(item => item.key)).size === 6, 'Source processing is incomplete.');
  const expected = [run.inputs.websitePages, run.inputs.sitemap, run.inputs.brief, run.inputs.assets, run.inputs.systems, packet.pages];
  for (let i = 0; i < 6; i++) check(run.receipts[i].key === WEBSITE_SIMULATION_STEPS[i].key && run.receipts[i].mode === 'simulated' && run.receipts[i].provider_api_called === false && run.receipts[i].input_sha256 === await websiteSimulationHash(expected[i]), 'A source receipt failed verification.');
  if (run.approval) check(run.approval.simulated === true && run.approval.status === 'approved_for_simulation_only' && run.approval.content_sha256 === run.content_sha256 && run.approval.assets_sha256 === await websiteSimulationHash(run.inputs.assets), 'The demo approval no longer matches the package.');
}

export async function stageWebsiteSimulation(packet, { onStep = () => {}, adapterFactory = createSimulatedWebsiteAdapter } = {}) {
  await verifyPrepared(packet);
  check(packet.simulationExecution.status === 'awaiting_demo_approval' && packet.simulationExecution.tools.length === 0, 'Start a new simulation rather than staging the same run twice.');
  check(packet.simulationExecution.approval, 'Approve the sample copy and images before staging simulated drafts.');
  const result = clone(packet), run = result.simulationExecution;
  run.receipts.push(await receipt('approval', run.approval, onStep));
  const preview = websiteCMSPreview(result);
  for (const output of preview.tools) {
    const key = output.id.replace('-preview', '');
    await onStep({ key, status: 'running' });
    const adapter = adapterFactory(key, run.id, result.pages);
    check(adapter.health().simulated && !adapter.health().realConnectionVerified, `${output.name}: expected an isolated simulation adapter.`);
    const before = adapter.liveSnapshot(), created = [];
    for (const page of output.pages) {
      const written = adapter.createDraft(page);
      const readback = adapter.readDraft(page.page_id);
      check(canonical(readback) === canonical(written) && readback.simulated && readback.id.startsWith(`SIM-${run.id}-`), `${output.name}: the draft readback did not match the created record.`);
      const normalized = readNative(key, readback);
      check(normalized.unpublished && normalized.title === page.title && normalized.body === page.body_html && canonical(normalized.seo) === canonical(page.seo) && canonical(normalized.images) === canonical(page.asset_requirements), `${output.name}: page copy, search listing, images or unpublished status failed readback.`);
      created.push({ ...page, simulated_record_id: readback.id, approval_status: 'approved_for_simulation_only', readback_verified: true, provider_record: readback, record_sha256: await websiteSimulationHash(readback) });
    }
    check(canonical(before) === canonical(adapter.liveSnapshot()), `${output.name}: a protected live-page fixture changed.`);
    const operations = adapter.operations();
    check(operations.filter(item => item.operation === 'create_draft').length === 5 && operations.filter(item => item.operation === 'read_draft').length === 5, `${output.name}: incomplete draft operations.`);
    run.tools.push({ ...output, status: 'simulated_drafts_verified', execution_mode: run.mode, pages: created, operations, simulated_records_created: 5, verified_readbacks: 5, protected_live_before: before, protected_live_after: adapter.liveSnapshot(), protected_live_sha256: await websiteSimulationHash(before) });
    run.receipts.push({ key, id: crypto.randomUUID(), executed_at: new Date().toISOString(), mode: 'simulated', provider_api_called: false, input_sha256: await websiteSimulationHash(output.pages), creates: 5, readbacks: 5 });
    await onStep({ key, status: 'completed' });
  }
  run.simulated_records_created = 20; run.verified_readbacks = 20;
  run.receipts.push(await receipt('handoff', run.tools.map(tool => ({ id: tool.id, records: tool.pages.map(page => page.record_sha256) })), onStep));
  run.status = 'completed'; run.completed_at = new Date().toISOString(); run.completed_steps = 12;
  await verifyWebsiteSimulation(result);
  return result;
}

export async function verifyWebsiteSimulation(packet) {
  await verifyPrepared(packet);
  const run = packet.simulationExecution;
  if (run.status === 'awaiting_demo_approval') {
    check(run.receipts.length === 6 && run.tools.length === 0 && run.simulated_records_created === 0 && run.verified_readbacks === 0, 'The review-stage simulation cannot contain draft staging claims.');
    return packet;
  }
  check(run.status === 'completed' && run.approval && run.completed_steps === 12 && run.receipts.length === 12 && run.simulated_records_created === 20 && run.verified_readbacks === 20, 'The simulated workflow did not complete.');
  const previews = websiteCMSPreview(packet).tools;
  check(run.tools.length === 4 && new Set(run.tools.map(tool => tool.id)).size === 4, 'Four distinct tool outcomes are required.');
  const ids = new Set();
  for (let index = 0; index < previews.length; index++) {
    const expected = previews[index], tool = run.tools[index], key = expected.id.replace('-preview', '');
    check(tool.id === expected.id && tool.status === 'simulated_drafts_verified' && tool.pages.length === 5 && tool.simulated_records_created === 5 && tool.verified_readbacks === 5 && tool.external_calls === 0 && tool.remote_records_created === 0 && tool.connection_verified === false, 'A simulated tool outcome is incomplete or mislabelled.');
    const live = packet.pages.map(page => ({ id: `protected-live-${page.page_id}`, url: page.url, original: clone(page.original), status: 'published' }));
    check(canonical(tool.protected_live_before) === canonical(live) && canonical(tool.protected_live_after) === canonical(live) && tool.protected_live_sha256 === await websiteSimulationHash(live), 'A protected live-page fixture changed.');
    for (let i = 0; i < 5; i++) {
      const page = tool.pages[i], base = expected.pages[i], record = page.provider_record;
      check(page.page_id === base.page_id && page.readback_verified === true && page.approval_status === 'approved_for_simulation_only', 'A page has no verified simulated readback.');
      check(canonical(Object.fromEntries(Object.keys(base).filter(field => field !== 'approval_status').map(field => [field, page[field]]))) === canonical(Object.fromEntries(Object.entries(base).filter(([field]) => field !== 'approval_status'))), 'A rendered page does not match its source content.');
      check(record.id === `SIM-${run.id}-${key}-${page.page_id}` && !ids.has(record.id) && page.simulated_record_id === record.id && record.simulated === true, 'A simulated draft ID is invalid or duplicated.'); ids.add(record.id);
      check(canonical(record) === canonical({ id: record.id, simulated: true, ...nativePayload(key, base) }) && page.record_sha256 === await websiteSimulationHash(record) && readNative(key, record).unpublished, 'The saved CMS draft content or publish state changed.');
      for (const operation of ['create_draft', 'read_draft']) check(tool.operations.filter(item => item.operation === operation && item.page_id === page.page_id && item.record_id === record.id && item.simulated === true).length === 1, 'A draft operation receipt is missing.');
    }
    check(tool.operations.length === 10, 'Unexpected tool operations.');
    check(run.receipts[index + 7].key === key && run.receipts[index + 7].input_sha256 === await websiteSimulationHash(expected.pages) && run.receipts[index + 7].creates === 5 && run.receipts[index + 7].readbacks === 5, 'A tool receipt changed.');
  }
  check(run.receipts[6].key === 'approval' && run.receipts[6].input_sha256 === await websiteSimulationHash(run.approval), 'The approval receipt changed.');
  check(run.receipts[11].key === 'handoff' && run.receipts[11].input_sha256 === await websiteSimulationHash(run.tools.map(tool => ({ id: tool.id, records: tool.pages.map(page => page.record_sha256) }))), 'The developer handoff receipt changed.');
  return packet;
}
