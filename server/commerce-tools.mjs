import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import { commerceToolResponse, COMMERCE_TOOLS, COMMERCE_ARGS, COMMERCE_SCHEMA, validCommerceArguments } from '../src/lib/commerceToolContract.mjs';

const json = (response, status, value) => { response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Access-Control-Allow-Origin': '*' }); response.end(JSON.stringify(value)); };
export function createCommerceServer() {
  return createServer(async (request, response) => {
    const url = new URL(request.url, 'http://localhost');
    const origin = process.env.RENDER_EXTERNAL_URL || 'http://' + request.headers.host;
    if (request.method === 'OPTIONS') { response.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Access-Control-Allow-Headers': 'content-type,mcp-protocol-version,mcp-session-id' }); return response.end(); }
    if (request.method === 'GET' && (url.pathname === '/health' || url.pathname === '/')) return json(response, 200, { status: 'ok', mode: 'simulated', tools: Object.values(COMMERCE_TOOLS).map(t => t.name), vendor_api_called: false });
    const report = /^\/reports\/(seller|google|meta|amazon)$/.exec(url.pathname);
    if (request.method === 'GET' && report) return json(response, 200, await commerceToolResponse(report[1], COMMERCE_ARGS, origin));
    const match = /^\/(seller|google|meta|amazon)\/mcp$/.exec(url.pathname);
    if (!match) return json(response, 404, { error: 'Not found' });
    if (request.method !== 'POST') return json(response, 405, { error: 'Stateless MCP uses POST only' });
    let body = '';
    try {
      for await (const chunk of request) { body += chunk; if (body.length > 16000) { json(response, 413, { error: 'Only bounded scenario arguments are accepted' }); return; } }
      const message = JSON.parse(body), tool = COMMERCE_TOOLS[match[1]];
      if (message.id === undefined) { response.writeHead(202); return response.end(); }
      const reply = result => json(response, 200, { jsonrpc: '2.0', id: message.id, result });
      if (message.method === 'initialize') return reply({ protocolVersion: message.params?.protocolVersion || '2025-03-26', capabilities: { tools: { listChanged: false } }, serverInfo: { name: tool.name + ' — Simulated', version: '1.0.0' }, instructions: 'Fictional demonstration data only. Read and draft proposals only; no vendor access or publishing.' });
      if (message.method === 'ping') return reply({});
      if (message.method === 'tools/list') return reply({ tools: [{ name: tool.operation, title: tool.name + ' weekly review — simulated', description: 'Read the authorized fictional product scenario, compare both complete reporting weeks, return source rows, attributed outcomes and draft proposals. This is a simulated ' + tool.name + ' connector, not a vendor API. There are no write capabilities.', inputSchema: COMMERCE_SCHEMA, outputSchema: { type: 'object', required: ['tool_key','synthetic','comparison','receipt'], properties: { tool_key: { type: 'string' }, synthetic: { type: 'boolean', enum: [true] }, comparison: { type: 'object' }, receipt: { type: 'object' } } }, annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } }] });
      if (message.method === 'tools/call') {
        if (message.params?.name !== tool.operation || !validCommerceArguments(message.params.arguments)) return reply({ isError: true, content: [{ type: 'text', text: 'Only this named read-only simulator and its exact scenario arguments are accepted.' }] });
        const result = await commerceToolResponse(match[1], message.params.arguments, origin);
        console.log(JSON.stringify({ operation: tool.operation, receipt: result.receipt.id, completed_at: result.receipt.executed_at, simulated: true }));
        return reply({ isError: false, content: [{ type: 'text', text: JSON.stringify(result) }], structuredContent: result });
      }
      return json(response, 200, { jsonrpc: '2.0', id: message.id, error: { code: -32601, message: 'Method not found' } });
    } catch { return json(response, 400, { error: 'Invalid bounded MCP request' }); }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const server = createCommerceServer();
  server.listen(Number(process.env.PORT || 10000), '0.0.0.0', () => console.log('Four simulated commerce MCP tools ready'));
  process.on('SIGTERM', () => server.close(() => process.exit(0)));
}
