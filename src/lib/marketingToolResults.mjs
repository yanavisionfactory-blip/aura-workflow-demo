const simulatedOperations = new Set(['meta-ads-simulated.review.get', 'klaviyo-simulated.lifecycle.get']);

export function marketingToolResult(outputs = []) {
  const simulations = outputs.filter(output => simulatedOperations.has(output.operation)
    && output.provider_result?.kind === 'marketing_tool'
    && output.provider_result?.synthetic === true
    && output.provider_result?.receipt?.mode === 'browser_simulated_tool_adapter'
    && output.provider_result?.receipt?.provider_api_called === false
    && output.provider_result?.receipt?.external_writes === false);
  if (!simulations.length) return null;
  if (outputs.length === 1) return {kind: 'marketing_tool', title: simulations[0].provider_result.tool,
    provider: simulations[0].provider_result.tool + ' · Simulated', packet: simulations[0].provider_result};
  return {kind: 'marketing_tools', title: 'Campaign workspace — Maple & Ember Coffee',
    completionTitle: 'Marketing tool outputs ready for review',
    completionSummary: 'Google Ads and Mailchimp native account checks, with separately executed Meta Ads and Klaviyo simulations. Same-client mapping and implementation approvals remain open.',
    packet: {simulations: simulations.map(output => output.provider_result)}, link: null};
}

export function parseMarketingDelivery(data) {
  const packets=data?.packet?.simulations;
  if(data?.kind!=='marketing_tools' || data.schemaVersion!==1 || !Array.isArray(packets) || packets.length!==2
    || new Set(packets.map(item=>item.tool)).size!==2
    || !packets.every(item=>['Meta Ads','Klaviyo'].includes(item.tool) && item.synthetic===true
      && item.receipt?.mode==='browser_simulated_tool_adapter'
      && item.receipt?.provider_api_called===false && item.receipt?.external_writes===false
      && item.receipt?.native_drafts_saved===false && /^[a-f0-9]{64}$/.test(item.receipt?.fixture_sha256)
      && Array.isArray(item.rows) && Array.isArray(item.drafts) && item.comparison?.current)) {
    throw new Error('Choose valid, explicitly simulated marketing tool results.');
  }
  if(data.sourceRunId && !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(data.sourceRunId)) throw new Error('Invalid native source-run reference.');
  return data;
}

export function marketingToolStates(activity = []) {
  const definitions = [
    {key:'google',name:'Google Ads',mode:'Native',operation:'google-ads.list-account-id-options'},
    {key:'meta',name:'Meta Ads',mode:'Simulated',operation:'meta-ads-simulated.review.get'},
    {key:'mailchimp',name:'Mailchimp',mode:'Native',operation:'mailchimp.audiences.list'},
    {key:'klaviyo',name:'Klaviyo',mode:'Simulated',operation:'klaviyo-simulated.lifecycle.get'},
  ];
  return definitions.map(tool => {
    const step = activity.find(item => (item.operation || item.output?.operation) === tool.operation);
    const response = step?.output?.provider_result;
    const status = response?.isError === true || response?.error ? 'provider_error' : step?.status || 'not_run';
    return {...tool, step, response, status,
      label: status === 'completed' ? (tool.mode === 'Simulated' ? 'Simulation completed' : 'Native read completed')
        : ['failed','blocked','skipped','provider_error'].includes(status) ? 'Needs attention' : 'Not completed'};
  });
}
