import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  Check,
  Copy,
  ExternalLink,
  Loader2,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { autoconnectAgent } from "@/lib/auraApi";
import { agentAutoconnectPayload, semrushApiKeySource } from "@/lib/agentConnections.mjs";
import { sitebulbApprovalRequest } from "@/lib/providerSetupRequest.mjs";

const DISCOVERY_STEPS = [
  "Finding the agent…",
  "Reading its skills…",
  "Checking safe access…",
];

function safeAuthorizationUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" ? parsed.toString() : "";
  } catch {
    return "";
  }
}

function ProviderApprovalRequest({ detail }) {
  const [copyStatus, setCopyStatus] = useState("");
  const request = sitebulbApprovalRequest(detail);
  if (!request) return null;
  const contents = `To: ${request.to}\nSubject: ${request.subject}\n\n${request.body}`;
  return <div className="space-y-2">
    <details className="rounded-lg border border-amber-400/15 p-2.5">
      <summary className="cursor-pointer font-medium text-primary">Review Sitebulb support request</summary>
      <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-[11px] leading-5 text-muted-foreground">{contents}</pre>
    </details>
    <button type="button" onClick={async () => {
      try { await navigator.clipboard.writeText(contents); setCopyStatus("Support request copied. Nothing was sent."); }
      catch { setCopyStatus("Copy is unavailable. You can select the request above."); }
    }} className="inline-flex items-center gap-1.5 rounded-lg border border-primary/25 px-3 py-2 text-primary"><Copy className="h-3 w-3" />Copy support request</button>
    {copyStatus && <p role="status" className="text-muted-foreground">{copyStatus}</p>}
  </div>;
}

export default function AgentConnectionForm({ onConnected = null }) {
  const [source, setSource] = useState("");
  const [credential, setCredential] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [phase, setPhase] = useState(0);
  const [error, setError] = useState("");
  const [authorizationUrl, setAuthorizationUrl] = useState("");
  const [registrationIssue, setRegistrationIssue] = useState(null);
  const [connectedAgent, setConnectedAgent] = useState(null);

  useEffect(() => {
    if (!connecting) {
      setPhase(0);
      return undefined;
    }
    const timer = window.setInterval(() => {
      setPhase((current) => Math.min(current + 1, DISCOVERY_STEPS.length - 1));
    }, 1100);
    return () => window.clearInterval(timer);
  }, [connecting]);

  const skillCount = useMemo(
    () => connectedAgent?.skills?.length || connectedAgent?.allowed_operations?.length || 0,
    [connectedAgent],
  );

  const connect = async (event) => {
    event.preventDefault();
    setConnecting(true);
    setError("");
    setAuthorizationUrl("");
    setRegistrationIssue(null);
    setConnectedAgent(null);
    try {
      const result = await autoconnectAgent(agentAutoconnectPayload({ source, credential }));
      setCredential("");
      setConnectedAgent(result);
      window.dispatchEvent(new CustomEvent("aura:agent-connected", { detail: result }));
      await onConnected?.(result);
    } catch (cause) {
      const detail = cause?.details?.detail;
      if (detail?.code === "provider_registration_rejected") setRegistrationIssue(detail);
      if (detail?.code === "agent_authorization_required") {
        setAuthorizationUrl(safeAuthorizationUrl(detail.authorization_url || source));
        setError(
          "This agent needs your permission. Approve AURA on the agent’s website, then try again.",
        );
      } else {
        setError(
          detail?.message || cause?.message || "AURA could not connect that agent.",
        );
      }
    } finally {
      setConnecting(false);
    }
  };

  return (
    <form onSubmit={connect} className="space-y-4">
      <div>
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Sparkles className="h-4 w-4 text-primary" />
          </div>
          <div>
            <h3 className="text-base font-semibold">Connect an agent</h3>
            <p className="text-[11px] text-muted-foreground">AURA handles the setup for you.</p>
          </div>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
          Paste the agent’s website or sharing link. AURA will find how it works,
          read its skills, and verify the connection automatically.
        </p>
      </div>

      <label className="block space-y-1.5 text-xs">
        <span className="font-medium">Agent website or sharing link</span>
        <input
          type="text"
          inputMode="url"
          value={source}
          onChange={(event) => {
            setSource(event.target.value);
            setCredential("");
            setConnectedAgent(null);
            setError("");
            setAuthorizationUrl("");
            setRegistrationIssue(null);
          }}
          placeholder="https://your-agent.com"
          autoComplete="url"
          className="w-full rounded-xl border border-white/10 bg-card px-3 py-2.5 outline-none transition-colors placeholder:text-muted-foreground/40 focus:border-primary/50"
        />
        <span className="block text-[10px] text-muted-foreground/70">
          Use the link from the agent’s Share or Connect page.
        </span>
      </label>

      {semrushApiKeySource(source) && (
        <label className="block space-y-1.5 text-xs">
          <span className="font-medium">Semrush API key (optional)</span>
          <input
            type="password"
            value={credential}
            onChange={(event) => setCredential(event.target.value)}
            maxLength={8000}
            autoComplete="off"
            spellCheck={false}
            placeholder="Enter your Semrush API key securely"
            className="w-full rounded-xl border border-white/10 bg-card px-3 py-2.5 outline-none focus:border-primary/50"
          />
          <span className="block text-[10px] leading-relaxed text-muted-foreground/70">
            Use a key with MCP access if OAuth setup is unavailable. AURA stores it encrypted
            and sends it only to Semrush. Leave blank to try OAuth. Never paste a key in chat.
          </span>
        </label>
      )}

      <div className="space-y-2 rounded-xl border border-white/8 bg-white/[0.025] p-3">
        {[
          "Find and understand the agent",
          "Verify the agent’s identity and skills",
          "Set safe access automatically",
        ].map((label, index) => (
          <div key={label} className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[9px] font-semibold text-primary">
              {index + 1}
            </span>
            {label}
          </div>
        ))}
      </div>

      {error && (
        <div className="rounded-xl border border-amber-400/20 bg-amber-400/5 p-3">
          <p className="text-xs leading-relaxed text-amber-200">{error}</p>
          {registrationIssue && <div aria-label="Provider setup requirements" className="mt-3 space-y-3 border-t border-amber-400/15 pt-3 text-[11px] leading-relaxed">
            <p className="font-semibold text-amber-200">{registrationIssue.requires_provider_approval ? "Sitebulb approval required" : "Provider setup required"}</p>
            <p className="text-muted-foreground">{registrationIssue.resolution}</p>
            <div><p className="font-medium text-muted-foreground">AURA callback to approve</p><code className="mt-1 block break-all rounded bg-black/20 p-2 text-primary">{registrationIssue.callback_url}</code></div>
            <div><p className="font-medium text-muted-foreground">Requested service</p><code className="block break-all text-muted-foreground">{registrationIssue.endpoint}</code></div>
            {registrationIssue.support_url === "https://sitebulb.com/support/" && <a href={registrationIssue.support_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-primary hover:underline">Open Sitebulb support<ExternalLink className="h-3 w-3" /></a>}
            <ProviderApprovalRequest detail={registrationIssue} />
            <p className="text-muted-foreground">No Sitebulb account credentials have been requested and no verified connection has been created.</p>
          </div>}
          {authorizationUrl && (
            <a
              href={authorizationUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-primary hover:underline"
            >
              Open agent to approve <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}

      {connectedAgent && (
        <div className="rounded-xl border border-emerald-400/20 bg-emerald-400/5 p-3">
          <div className="flex items-start gap-2">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-emerald-300">
                {connectedAgent.name} is ready
              </p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {skillCount} verified skill{skillCount === 1 ? "" : "s"} · safe access applied
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="flex gap-2 rounded-xl border border-emerald-400/15 bg-emerald-400/5 p-3 text-[11px] leading-relaxed text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
        <span>
          You approve what the agent receives. It never sees your Gmail, Canva,
          Drive, or other account credentials.
        </span>
      </div>

      <button
        type="submit"
        disabled={connecting || source.trim().length < 2}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
        {connecting ? DISCOVERY_STEPS[phase] : connectedAgent ? "Connected" : credential ? "Verify Semrush key" : "Let AURA connect it"}
      </button>
    </form>
  );
}
