import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  AGENT_METHODS,
  agentConnectionPayload,
  agentPromptHints,
} from "../src/lib/agentConnections.mjs";

test("offers A2A, MCP, and AURA Agent API connections", () => {
  assert.deepEqual(AGENT_METHODS.map((method) => method.id), ["a2a", "mcp", "aura"]);
});

test("normalizes a bounded agent connection payload", () => {
  assert.deepEqual(
    agentConnectionPayload({
      protocol: "A2A",
      name: "  Research   Agent ",
      owner: " Research Co ",
      endpoint: "https://agent.example.com/a2a/v1",
      authentication: "bearer",
      credential: "agent-secret",
      data_access: "approved brief, campaign metrics, approved brief",
      data_retention: "deleted after 30 days",
      max_runtime_seconds: "30",
      max_cost_usd: "2",
    }),
    {
      protocol: "a2a",
      name: "Research Agent",
      owner: "Research Co",
      endpoint: "https://agent.example.com/a2a/v1",
      authentication: "bearer",
      credential: "agent-secret",
      data_access: ["approved brief", "campaign metrics"],
      data_retention: "deleted after 30 days",
      max_runtime_seconds: 30,
      max_cost_usd: 2,
    },
  );
});

test("rejects insecure endpoints and missing agent credentials", () => {
  assert.throws(
    () => agentConnectionPayload({
      protocol: "mcp",
      name: "Research Agent",
      owner: "Research Co",
      endpoint: "http://agent.example.com/mcp",
    }),
    /must use HTTPS/,
  );
  assert.throws(
    () => agentConnectionPayload({
      protocol: "mcp",
      name: "Research Agent",
      owner: "Research Co",
      endpoint: "https://agent.example.com/mcp",
      authentication: "api_key",
    }),
    /Enter the credential/,
  );
  assert.throws(
    () => agentConnectionPayload({
      protocol: "aura",
      name: "Research Agent",
      owner: "Research Co",
      endpoint: "https://token@agent.example.com/invoke?debug=true",
    }),
    /cannot include credentials, query parameters, or fragments/,
  );
  assert.throws(
    () => agentConnectionPayload({
      protocol: "a2a",
      name: "Research Agent",
      owner: "Research Co",
      endpoint: "https://agent.example.com/a2a/v1",
      manifest_url: "https://different.example.com/agent-card.json",
    }),
    /must use the agent endpoint origin/,
  );
});

test("suggests only a connected verified agent named in the prompt", () => {
  const agents = [
    { name: "Research Agent", enabled: true, status: "verified" },
    { name: "Design Agent", enabled: false, status: "revoked" },
  ];

  assert.deepEqual(
    agentPromptHints("Ask Research Agent to compare the vendors", agents),
    ["Research Agent"],
  );
  assert.deepEqual(agentPromptHints("Ask Design Agent for a campaign", agents), []);
});

test("agent connection is reachable from both connection surfaces", () => {
  const command = readFileSync(
    new URL("../src/components/aura/CommandInput.jsx", import.meta.url),
    "utf8",
  );
  const menu = readFileSync(
    new URL("../src/components/aura/ConnectionsPill.jsx", import.meta.url),
    "utf8",
  );

  assert.equal(command.includes("Connect agent"), true);
  assert.equal(menu.includes('setTab("agents")'), true);
  assert.equal(menu.includes("<AgentConnectionForm"), true);
});
