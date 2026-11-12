import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { auraRequest } from "@/lib/auraApi";

export default function FrameioAssistantConnect() {
  const [params] = useSearchParams();
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const inFlight = useRef(false);
  const endpoint = state?.id && !state?.disconnected ? `/v1/frameio-assistant/sessions/${state.id}` : null;
  const request = async (path, options = {}) => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const data = await auraRequest(path, { timeoutMs: 60000, ...options });
      setState(old => ({ ...old, ...data }));
    } catch (e) { setError(e.message); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const input = (data) => endpoint && request(`${endpoint}/input`, { method: "POST", body: JSON.stringify(data) });
  useEffect(() => {
    if (!endpoint || state?.ready) return undefined;
    const timer = setInterval(() => {
      if (inFlight.current || document.hidden) return;
      auraRequest(endpoint, { timeoutMs: 15000 }).then(data => { if (!inFlight.current) setState(old => ({ ...old, ...data })); })
        .catch(e => { if (!inFlight.current) setError(e.message); });
    }, 2000);
    return () => clearInterval(timer);
  }, [endpoint, state?.ready]);
  const button = "rounded-lg border border-white/20 px-4 py-2 disabled:opacity-50";
  return <main className="min-h-screen bg-[#080d1b] p-6 text-white">
    <section className="mx-auto max-w-6xl space-y-4">
      <Link to="/" className="text-sm underline">Back to AURA</Link>
      <h1 className="text-2xl font-semibold">Connect Frame.io AI Assistant</h1>
      <p className="max-w-3xl text-sm text-slate-300">Sign in to your connected Frame.io account in this AURA browser. AURA uses this session to submit your selected video and review instructions to Frame.io’s own assistant and bring its reply back. This session expires after two hours or a browser service restart.</p>
      {error && <p role="alert" className="text-amber-300">{error}</p>}
      {!state?.id && <button className={button} disabled={busy || !params.get("account_id") || !params.get("file_id")} onClick={() => request("/v1/frameio-assistant/sessions", {
        method: "POST", body: JSON.stringify({ account_id: params.get("account_id"), file_id: params.get("file_id") }),
      })}>{busy ? "Opening Frame.io…" : "Open Frame.io sign-in"}</button>}
      {!params.get("account_id") && <p>Open this connection from your video workflow’s account checks.</p>}
      {state?.ready && !state?.disconnected ? <p role="status" className="rounded-xl border border-green-500/30 p-5 text-green-200">Frame.io AI Assistant is connected for this video. Return to your AURA workflow, select “Check again,” and start the review.</p> : state?.id && !state?.disconnected && <>
        <p className="text-sm">{state.account && `Use ${state.account}. `}Current sign-in site: <strong>{state.site}</strong>. Click inside the browser image, then type using the secure field below. Complete any verification yourself.</p>
        <div className="flex flex-wrap gap-2">
          <input aria-label="Text for the focused Frame.io sign-in field" type="password" autoComplete="off" value={text} onChange={e => setText(e.target.value)} className="min-w-64 rounded-lg bg-white/10 p-2" />
          <button className={button} disabled={busy || !text} onClick={() => { const value = text; setText(""); void input({ action: "text", text: value }); }}>Type into focused field</button>
          {["Tab", "Enter", "Backspace", "Control+A"].map(key => <button key={key} className={button} disabled={busy} onClick={() => input({ action: "key", key })}>{key === "Control+A" ? "Select all" : key}</button>)}
          <button className={button} disabled={busy} onClick={() => input({ action: "verify" })}>I’m signed in — check access</button>
        </div>
        {state.screenshot && <img tabIndex={0} alt="AURA browser showing Frame.io sign-in" className="w-full rounded-lg border border-white/20" src={`data:image/jpeg;base64,${state.screenshot}`}
          onClick={e => { const box = e.currentTarget.getBoundingClientRect(); void input({ action: "click", x: Math.min(1439, Math.floor((e.clientX - box.left) * 1440 / box.width)), y: Math.min(999, Math.floor((e.clientY - box.top) * 1000 / box.height)) }); }} />}
        <div className="flex gap-2">{[-600, 600].map(delta => <button className={button} disabled={busy} key={delta} onClick={() => input({ action: "scroll", delta })}>{delta < 0 ? "Scroll up" : "Scroll down"}</button>)}</div>
      </>}
      {state?.id && !state?.disconnected && <button disabled={busy} className={button} onClick={async () => {
        await request(endpoint, { method: "DELETE" });
      }}>Disconnect assistant session</button>}
      {state?.disconnected && <p role="status">Session disconnected. Close this page.</p>}
    </section>
  </main>;
}
