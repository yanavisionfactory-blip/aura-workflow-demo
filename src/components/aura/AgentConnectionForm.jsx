import { useMemo, useState } from "react";
import { Bot, Braces, Check, KeyRound, Loader2, Network } from "lucide-react";

import { connectAgentConnection } from "@/lib/auraApi";
import { AGENT_METHODS, agentConnectionPayload } from "@/lib/agentConnections.mjs";

const METHOD_ICONS = { a2a: Network, mcp: Braces, aura: Bot };

const INITIAL = {
  protocol: "a2a",
  name: "",
  owner: "",
  endpoint: "",
  manifest_url: "",
  authentication: "none",
  credential: "",
  data_access: "",
  data_retention: "provider-defined",
  max_runtime_seconds: 30,
  max_cost_usd: 5,
};

export default function AgentConnectionForm({ onConnected }) {
  const [draft, setDraft] = useState(INITIAL);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState("");
  const [connectedAgent, setConnectedAgent] = useState(null);
  const method = useMemo(
    () => AGENT_METHODS.find((item) => item.id === draft.protocol),
    [draft.protocol],
  );

  const update = (key, value) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setConnectedAgent(null);
  };

  const connect = async (event) => {
    event.preventDefault();
    setConnecting(true);
    setError("");
    try {
      const result = await connectAgentConnection(agentConnectionPayload(draft));
      setConnectedAgent(result);
      setDraft((current) => ({ ...current, credential: "" }));
      window.dispatchEvent(new CustomEvent("aura:agent-connected", { detail: result }));
      await onConnected?.(result);
    } catch (cause) {
      setError(cause?.message || "AURA could not connect that agent.");
    } finally {
      setConnecting(false);
    }
  };

  return (
    <form onSubmit={connect} className="space-y-4">
      <div>
        <h3 className="text-base font-semibold">Connect an agent</h3>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          AURA verifies the agent’s declared skills and keeps control of approvals,
          credentials, and workflow state.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2" aria-label="Agent connection method">
        {AGENT_METHODS.map((item) => {
          const Icon = METHOD_ICONS[item.id];
          const selected = draft.protocol === item.id;
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={selected}
              onClick={() => update("protocol", item.id)}
              className={`rounded-xl border p-2.5 text-left transition-colors ${selected ? "border-primary/50 bg-primary/10 text-primary" : "border-white/10 hover:bg-white/5"}`}
            >
              <Icon className="mb-2 h-4 w-4" />
              <span className="block text-xs font-semibold">{item.name}</span>
            </button>
          );
        })}
      </div>
      <p className="-mt-2 text-[11px] text-muted-foreground">{method?.description}</p>

      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1.5 text-xs">
          <span className="font-medium">Agent name</span>
          <input
            value={draft.name}
            onChange={(event) => update("name", event.target.value)}
            placeholder="Marketing Strategy Agent"
            className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 outline-none focus:border-primary/50"
          />
        </label>
        <label className="space-y-1.5 text-xs">
          <span className="font-medium">Owner or organization</span>
          <input
            value={draft.owner}
            onChange={(event) => update("owner", event.target.value)}
            placeholder="Example, Inc."
            className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 outline-none focus:border-primary/50"
          />
        </label>
      </div>

      <label className="block space-y-1.5 text-xs">
        <span className="font-medium">Agent endpoint</span>
        <input
          type="url"
          value={draft.endpoint}
          onChange={(event) => update("endpoint", event.target.value)}
          placeholder={method?.endpointPlaceholder}
          className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 outline-none focus:border-primary/50"
        />
      </label>

      {draft.protocol !== "mcp" && (
        <label className="block space-y-1.5 text-xs">
          <span className="font-medium">Manifest URL <span className="text-muted-foreground">(optional)</span></span>
          <input
            type="url"
            value={draft.manifest_url}
            onChange={(event) => update("manifest_url", event.target.value)}
            placeholder={draft.protocol === "a2a" ? "Uses /.well-known/agent-card.json by default" : "Uses /.well-known/aura-agent.json by default"}
            className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 outline-none focus:border-primary/50"
          />
        </label>
      )}

      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1.5 text-xs">
          <span className="font-medium">Authentication</span>
          <select
            value={draft.authentication}
            onChange={(event) => update("authentication", event.target.value)}
            className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 outline-none focus:border-primary/50"
          >
            <option value="none">No authentication</option>
            <option value="bearer">Bearer token</option>
            <option value="api_key">API key</option>
          </select>
        </label>
        {draft.authentication !== "none" && (
          <label className="space-y-1.5 text-xs">
            <span className="font-medium">Agent credential</span>
            <div className="flex items-center rounded-lg border border-white/10 bg-card px-3 focus-within:border-primary/50">
              <KeyRound className="h-3.5 w-3.5 text-muted-foreground" />
              <input
                type="password"
                value={draft.credential}
                onChange={(event) => update("credential", event.target.value)}
                autoComplete="new-password"
                className="min-w-0 flex-1 bg-transparent px-2 py-2 outline-none"
              />
            </div>
          </label>
        )}
      </div>

      <label className="block space-y-1.5 text-xs">
        <span className="font-medium">Data the agent may receive <span className="text-muted-foreground">(comma-separated)</span></span>
        <input
          value={draft.data_access}
          onChange={(event) => update("data_access", event.target.value)}
          placeholder="campaign metrics, approved brief"
          className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 outline-none focus:border-primary/50"
        />
      </label>

      <label className="block space-y-1.5 text-xs">
        <span className="font-medium">Data-retention policy</span>
        <input
          value={draft.data_retention}
          onChange={(event) => update("data_retention", event.target.value)}
          placeholder="provider-defined"
          className="w-full rounded-lg border border-white/10 bg-card px-3 py-2 outline-none focus:border-primary/50"
        />
      </label>

      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1.5 text-xs">
          <span className="font-medium">Runtime limit</span>
          <div className="flex items-center rounded-lg border border-white/10 bg-card pr-3 focus-within:border-primary/50">
            <input
              type="number"
              min="5"
              max="300"
              value={draft.max_runtime_seconds}
              onChange={(event) => update("max_runtime_seconds", event.target.value)}
              className="min-w-0 flex-1 bg-transparent px-3 py-2 outline-none"
            />
            <span className="text-muted-foreground">seconds</span>
          </div>
        </label>
        <label className="space-y-1.5 text-xs">
          <span className="font-medium">Cost ceiling</span>
          <div className="flex items-center rounded-lg border border-white/10 bg-card px-3 focus-within:border-primary/50">
            <span className="text-muted-foreground">$</span>
            <input
              type="number"
              min="0"
              max="1000"
              step="0.01"
              value={draft.max_cost_usd}
              onChange={(event) => update("max_cost_usd", event.target.value)}
              className="min-w-0 flex-1 bg-transparent px-2 py-2 outline-none"
            />
          </div>
        </label>
      </div>

      <div className="rounded-xl border border-emerald-400/15 bg-emerald-400/5 p-3 text-[11px] leading-relaxed text-muted-foreground">
        The agent can return artifacts only. It never receives Gmail, Canva, Drive,
        or other AURA connector credentials, and it cannot call those tools.
      </div>

      {error && (
        <p className="rounded-lg border border-red-400/20 bg-red-400/5 p-2 text-xs text-red-400">
          {error}
        </p>
      )}
      {connectedAgent && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-400/20 bg-emerald-400/5 p-3">
          <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
          <div>
            <p className="text-xs font-medium text-emerald-400">
              {connectedAgent.name} is connected
            </p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {connectedAgent.skills?.length || connectedAgent.allowed_operations?.length || 0} verified skill{(connectedAgent.skills?.length || connectedAgent.allowed_operations?.length || 0) === 1 ? "" : "s"} · {String(connectedAgent.protocol || "").toUpperCase()}
            </p>
          </div>
        </div>
      )}

      <button
        type="submit"
        disabled={connecting}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
        {connecting ? "Discovering and verifying…" : "Connect agent"}
      </button>
    </form>
  );
}
