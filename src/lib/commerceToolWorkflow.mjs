import { COMMERCE_ORDER, COMMERCE_TOOLS, COMMERCE_ARGS, commerceRunSteps, validCommerceArguments, validateCommercePlan, buildCommerceDelivery } from './commerceToolContract.mjs';

export const COMMERCE_ENDPOINT = 'https://aura-commerce-tools.onrender.com';
export function commerceWorkflowPrompt(connections) {
  return `Execute a weekly marketing review for the fictional Unstoprev client Harbor & Field / Everyday Travel Mug B0SIMMUG16. The user explicitly authorized SIMULATED data. Use EXACTLY FOUR connected simulation tools and exactly the following operations, no AURA Intelligence, report.compose, weekly.source.analyze, account discovery, real vendor account, external document, task or message operation:\n${COMMERCE_ORDER.map(key => `${key}: tool_slug=${connections[key].slug}; operation=${COMMERCE_TOOLS[key].operation}; arguments=${JSON.stringify(COMMERCE_ARGS)}; ${key === 'seller' ? 'execute FIRST, inspect listing, total ASIN sales, traffic, conversion and available inventory' : 'depends_on seller; compare both complete reporting weeks, inspect this advertising platform and return its proposed test and copy'}`).join('\n')}\nAll reports use October12–18 versus October5–11 2026, America/Chicago, USD. Each remote tool returns its own simulated raw source rows, derived metrics, attribution definitions, proposed test/copy and real MCP execution receipt. Retain all four distinct outputs. Do not replace tool calls with prose. After the four calls, summarize actual returned results in AURA without another tool step. Keep website purchases, each platform attributed sales, and Amazon total ASIN sales separate. Seller available stock must be checked before recommending promotion. All copy, tests and checklist actions remain proposals for account-manager review. No ad, budget, listing or inventory change. The simulation services have no vendor credentials and no publishing capabilities. No real client identity mapping or account consent is requested. Scope is exactly these four connected simulators.`;
}

export async function runCommerceTools(api, update = () => {}, options = {}) {
  const connections = {};
  for (const key of COMMERCE_ORDER) {
    update({ phase: 'connecting', key, message: 'Verifying ' + COMMERCE_TOOLS[key].name + ' simulation connector' });
    connections[key] = await api.connect({ protocol: 'mcp', name: COMMERCE_TOOLS[key].name + ' · Simulated', owner: 'Unstoprev fictional commerce scenario', endpoint: COMMERCE_ENDPOINT + '/' + key + '/mcp', authentication: 'none', data_access: ['Fixed fictional product and simulated reporting data only'], data_retention: 'No user data or vendor credentials retained; fixed public scenario', max_runtime_seconds: 30, max_cost_usd: 0 });
  }
  let run = await api.createRun(commerceWorkflowPrompt(connections), null, options.requestKey || crypto.randomUUID(), { requested_tools: COMMERCE_ORDER.map(key => connections[key].name || COMMERCE_TOOLS[key].name + ' · Simulated') });
  options.remember?.(run.id);
  let planApproved = false, finalRetries = 0;
  const approved = new Set();
  const pause = options.pause || (ms => new Promise(resolve => setTimeout(resolve, ms)));
  for (let count = 0; count < (options.maxPolls || 600); count++) {
    run = await api.getRun(run.id);
    update({ phase: run.status, run, connections, message: run.public_status === 'finalizing' ? 'AURA is verifying the four saved tool receipts' : run.status.replaceAll('_',' ') });
    if (run.status === 'completed') return buildCommerceDelivery(run, connections);
    if (run.status === 'awaiting_approval' && !run.plan_approved && !planApproved) {
      validateCommercePlan(run.plan, connections);
      await api.approvePlan(run.id, commerceRunSteps(connections, run.plan), false);
      planApproved = true;
    }
    for (const step of run.steps || []) {
      if (step.status !== 'awaiting_approval' || step.approval_status !== 'pending' || approved.has(step.approval_id)) continue;
      const key = COMMERCE_ORDER.find(key => COMMERCE_TOOLS[key].operation === step.operation && connections[key].slug === step.tool_slug);
      if (!key || step.approval_preview?.status !== 'ready' || !validCommerceArguments(step.approval_preview.arguments)) throw new Error('The native approval differs from the exact four authorized simulation reads. Open the saved run to review it.');
      await api.decideApproval(step.approval_id, true);
      approved.add(step.approval_id);
    }
    if (['failed','waiting_for_action','blocked'].includes(run.status)) {
      if (run.blocker?.action === 'retry_final_review' && finalRetries < 2) { finalRetries++; await api.resume(run.id); }
      else throw new Error((run.blocker?.message || run.error || 'AURA needs review before continuing') + ' Saved run: ' + run.id);
    }
    if (['cancelled','waiting_for_connection'].includes(run.status)) throw new Error(run.blocker?.message || 'AURA did not execute all four tools. The saved run remains available.');
    await pause(2000);
  }
  throw new Error('The native workflow is still running. Open its saved run to continue: ' + run.id);
}
