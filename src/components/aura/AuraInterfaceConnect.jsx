import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  ArrowLeft,
  Globe,
  Loader2,
  Check,
  Eye,
  Hand,
  ShieldCheck,
  Sparkles,
  Plug,
  AlertTriangle,
  Lock,
} from "lucide-react";
import { aura } from "@/api/auraClient";

// AURA Interface — REAL site analysis. Calls the analyzeToolInterface backend
// function, which fetches the URL server-side, extracts the actual DOM
// structure, and asks the LLM to interpret real capabilities from it.
//
// Steps: intro → url → analyzing (live) → found (real capabilities) or
// blocked (login wall / thin content / fetch error).

const PROGRESS_STEPS = [
  "Opening the site…",
  "Reading the page structure…",
  "Finding forms, inputs, and actions…",
  "Interpreting what this tool can do…",
];

const KIND_ICON = { view: Eye, do: Hand, change: ShieldCheck };

export default function AuraInterfaceConnect({ open, toolName, onClose, onConnect }) {
  const [step, setStep] = useState("intro"); // intro | url | analyzing | found | blocked
  const [url, setUrl] = useState("");
  const [progressIdx, setProgressIdx] = useState(0);
  const [analysis, setAnalysis] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setStep("intro");
      setUrl("");
      setProgressIdx(0);
      setAnalysis(null);
      setError("");
    }
  }, [open, toolName]);

  // Drive the progress indicators while analyzing. The real work is the
  // backend call; these steps just give the user visible feedback.
  useEffect(() => {
    if (step !== "analyzing") return;
    setProgressIdx(0);
    const timers = [];
    PROGRESS_STEPS.forEach((_, i) => {
      timers.push(setTimeout(() => setProgressIdx(i + 1), 700 * (i + 1)));
    });
    return () => timers.forEach(clearTimeout);
  }, [step]);

  const runAnalysis = async () => {
    setStep("analyzing");
    setError("");
    setAnalysis(null);
    try {
      const res = await aura.functions.invoke("analyzeToolInterface", { url });
      const data = res.data || {};
      if (data.error) throw new Error(data.error);
      setAnalysis(data.analysis);
      // Login-gated or near-empty pages are surfaced honestly, not faked.
      if (data.analysis?.loginRequired || data.analysis?.thinContent) {
        setStep("blocked");
      } else {
        setStep("found");
      }
    } catch (e) {
      setError(e.message || "Could not analyze this site.");
      setStep("blocked");
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
          />
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="fixed right-0 top-0 h-full w-full max-w-md z-50 bg-card border-l border-white/6 flex flex-col shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/6">
              <div className="flex items-center gap-2">
                {step !== "intro" && step !== "found" && step !== "blocked" ? (
                  <button
                    onClick={() => setStep(step === "analyzing" ? "url" : "intro")}
                    className="p-1.5 -ml-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <ArrowLeft className="w-4 h-4" />
                  </button>
                ) : (
                  <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
                    <Sparkles className="w-4 h-4 text-primary" />
                  </div>
                )}
                <span className="font-semibold text-sm">Connect a tool</span>
              </div>
              <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/5 text-muted-foreground hover:text-foreground transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-5">
              <AnimatePresence mode="wait">
                {/* Intro */}
                {step === "intro" && (
                  <motion.div
                    key="intro"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    className="flex flex-col h-full"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Plug className="w-4 h-4 text-primary" />
                      <h3 className="text-base font-semibold">Connect {toolName}</h3>
                    </div>
                    <p className="text-sm text-muted-foreground leading-relaxed mb-5">
                      AURA doesn't have a standard connection for this tool.
                    </p>
                    <div className="rounded-xl border border-primary/20 bg-primary/[0.06] p-4 mb-6">
                      <p className="text-sm leading-relaxed">
                        I can learn how you use it instead. Paste the tool's address and AURA will
                        analyze its interface to figure out what it can do — you'll approve every
                        action before it runs.
                      </p>
                    </div>
                    <div className="space-y-2 mb-6">
                      {[
                        { icon: Eye, label: "AURA reads the tool's interface" },
                        { icon: Sparkles, label: "Learns what it can view, do, and change" },
                        { icon: ShieldCheck, label: "You approve before anything is submitted" },
                      ].map((r, i) => (
                        <div key={i} className="flex items-center gap-3 text-sm text-muted-foreground">
                          <r.icon className="w-4 h-4 text-primary/70 flex-shrink-0" />
                          <span>{r.label}</span>
                        </div>
                      ))}
                    </div>
                    <div className="mt-auto">
                      <button
                        onClick={() => setStep("url")}
                        className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                      >
                        Continue
                      </button>
                    </div>
                  </motion.div>
                )}

                {/* URL */}
                {step === "url" && (
                  <motion.div
                    key="url"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    className="flex flex-col h-full"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Globe className="w-4 h-4 text-primary" />
                      <h3 className="text-base font-semibold">Paste the tool's address</h3>
                    </div>
                    <p className="text-sm text-muted-foreground leading-relaxed mb-4">
                      Share the link to {toolName}. AURA will open it and figure out how it works.
                    </p>
                    <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-card/70 border border-white/10 mb-2">
                      <Globe className="w-3.5 h-3.5 text-muted-foreground/60 flex-shrink-0" />
                      <input
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                        placeholder="https://your-tool.com"
                        className="flex-1 bg-transparent outline-none text-sm placeholder:text-muted-foreground/40"
                      />
                    </div>
                    <p className="text-[11px] text-muted-foreground/60 mb-6">
                      AURA fetches the page and reads its structure. Login-gated pages are detected
                      and reported honestly — AURA won't pretend to learn an app it can't see.
                    </p>
                    <div className="mt-auto">
                      <button
                        onClick={runAnalysis}
                        disabled={!url.trim()}
                        className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
                      >
                        Analyze
                      </button>
                    </div>
                  </motion.div>
                )}

                {/* Analyzing — real backend call in flight */}
                {step === "analyzing" && (
                  <motion.div
                    key="analyzing"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    className="flex flex-col h-full"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Loader2 className="w-4 h-4 text-primary animate-spin" />
                      <h3 className="text-base font-semibold">Understanding this tool…</h3>
                    </div>
                    <p className="text-sm text-muted-foreground leading-relaxed mb-5">
                      AURA is analyzing <span className="text-foreground/80">{url}</span>
                    </p>
                    <div className="space-y-2.5">
                      {PROGRESS_STEPS.map((label, i) => {
                        const done = i < progressIdx;
                        const active = i === progressIdx;
                        return (
                          <motion.div
                            key={label}
                            initial={{ opacity: 0.3 }}
                            animate={{ opacity: done || active ? 1 : 0.35 }}
                            className="flex items-center gap-3"
                          >
                            <div className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 border border-white/10">
                              {done ? (
                                <Check className="w-3 h-3 text-emerald-400" />
                              ) : active ? (
                                <Loader2 className="w-3 h-3 text-primary animate-spin" />
                              ) : (
                                <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground/30" />
                              )}
                            </div>
                            <span className={`text-sm ${done ? "text-foreground" : "text-muted-foreground"}`}>
                              {label}
                            </span>
                          </motion.div>
                        );
                      })}
                    </div>
                  </motion.div>
                )}

                {/* Found — real capabilities from the backend */}
                {step === "found" && analysis && (
                  <motion.div
                    key="found"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    className="flex flex-col h-full"
                  >
                    <div className="inline-flex items-center gap-1.5 text-[11px] text-emerald-400 mb-2">
                      <Check className="w-3.5 h-3.5" />
                      Analysis complete
                    </div>
                    <h3 className="text-base font-semibold mb-1">
                      I found what {analysis.toolName || toolName} can do
                    </h3>
                    <p className="text-sm text-muted-foreground mb-5">{analysis.summary}</p>

                    <div className="space-y-3 mb-6">
                      {(analysis.capabilities || []).map((cap, i) => {
                        const Icon = KIND_ICON[cap.kind] || Eye;
                        return (
                          <div key={i} className="flex items-start gap-3 p-3 rounded-xl border border-white/8 bg-card/40">
                            <div className="p-1.5 rounded-lg bg-primary/10 flex-shrink-0">
                              <Icon className="w-3.5 h-3.5 text-primary" />
                            </div>
                            <div>
                              <p className="text-[11px] text-muted-foreground/70 capitalize">{cap.kind}</p>
                              <p className="text-sm font-medium mt-0.5">{cap.label}</p>
                              <p className="text-xs text-muted-foreground mt-0.5">{cap.detail}</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {(analysis.forms || []).length > 0 && (
                      <div className="rounded-xl border border-white/8 bg-card/40 p-3 mb-6">
                        <p className="text-[11px] text-muted-foreground/70 mb-2">Forms detected</p>
                        <div className="space-y-1.5">
                          {analysis.forms.map((f, i) => (
                            <div key={i} className="text-xs">
                              <span className="font-medium">{f.purpose}</span>
                              {f.hasSubmit && <span className="text-muted-foreground"> · has submit</span>}
                              {f.fields?.length > 0 && (
                                <span className="text-muted-foreground"> · {f.fields.join(", ")}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="rounded-xl border border-white/8 bg-card/50 p-3 mb-6">
                      <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
                        AURA will always show this action in your plan before submitting it. You stay in control.
                      </p>
                    </div>

                    <div className="mt-auto">
                      <button
                        onClick={() => onConnect(analysis.toolName || toolName, { baseUrl: url, analysis })}
                        className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-gradient-to-r from-primary to-accent text-white text-sm font-semibold shadow-lg shadow-primary/20 hover:opacity-95 transition-opacity"
                      >
                        <ShieldCheck className="w-4 h-4" />
                        Allow &amp; Connect
                      </button>
                    </div>
                  </motion.div>
                )}

                {/* Blocked — honest: login wall, thin content, or fetch error */}
                {step === "blocked" && (
                  <motion.div
                    key="blocked"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    className="flex flex-col h-full"
                  >
                    <div className="inline-flex items-center gap-1.5 text-[11px] text-amber-400 mb-2">
                      {analysis?.loginRequired ? <Lock className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                      {analysis?.loginRequired ? "Login required" : analysis?.thinContent ? "Not enough to learn from" : "Couldn't analyze"}
                    </div>
                    <h3 className="text-base font-semibold mb-1">I can't learn this one — yet</h3>
                    <p className="text-sm text-muted-foreground mb-5">
                      {analysis?.loginRequired
                        ? `This page is behind a login. AURA fetched it and saw the sign-in screen, not the app itself — so there's nothing real to learn. ${
                            analysis.summary || ""
                          }`
                        : analysis?.thinContent
                        ? `AURA fetched the page but found almost no interactive structure — it's likely a client-rendered app that builds its interface with JavaScript after loading, so the raw HTML is mostly empty. ${
                            analysis.summary || ""
                          }`
                        : error || "AURA couldn't reach or read this site."}
                    </p>

                    {analysis?.forms?.length > 0 && (
                      <div className="rounded-xl border border-white/8 bg-card/40 p-3 mb-5">
                        <p className="text-[11px] text-muted-foreground/70 mb-2">What AURA did see</p>
                        <div className="space-y-1.5">
                          {analysis.forms.map((f, i) => (
                            <div key={i} className="text-xs">
                              <span className="font-medium">{f.purpose}</span>
                              {f.fields?.length > 0 && (
                                <span className="text-muted-foreground"> · {f.fields.join(", ")}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="rounded-xl border border-primary/20 bg-primary/[0.06] p-4 mb-6">
                      <p className="text-sm leading-relaxed">
                        To connect this for real, the tool needs either a public API or an OAuth
                        integration. If it has one, share the docs link and AURA can wire a real
                        connector instead.
                      </p>
                    </div>

                    <div className="mt-auto flex gap-2">
                      <button
                        onClick={() => setStep("url")}
                        className="flex-1 py-2.5 rounded-xl bg-white/5 border border-white/10 text-sm font-medium hover:bg-white/10 transition-colors"
                      >
                        Try another URL
                      </button>
                      <button
                        onClick={onClose}
                        className="flex-1 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                      >
                        Close
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
