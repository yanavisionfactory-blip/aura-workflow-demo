import { useState } from "react";
import { motion } from "framer-motion";
import { Shield, ShieldCheck, Zap, Eye, FileCheck2, ArrowRight } from "lucide-react";

const LEVELS = [
  {
    value: "review",
    icon: Eye,
    title: "Review every run",
    desc: "AURA pauses before each run so you can confirm the plan.",
    badge: "Most supervision",
    color: "text-amber-300",
    ring: "border-amber-400/40",
    bg: "bg-amber-400/10",
  },
  {
    value: "writes",
    icon: FileCheck2,
    title: "Only ask before sending or changing data",
    desc: "Reads happen automatically. AURA checks with you before any write or send.",
    badge: "Balanced",
    color: "text-accent",
    ring: "border-accent/40",
    bg: "bg-accent/10",
  },
  {
    value: "auto",
    icon: Zap,
    title: "Run automatically",
    desc: "AURA runs end-to-end and reports the outcome. You're notified if it needs you.",
    badge: "Most autonomy",
    color: "text-emerald-300",
    ring: "border-emerald-400/40",
    bg: "bg-emerald-400/10",
  },
];

export default function TrustLadder({ runCount = 1, actionLabel = "Run now", onConfirm }) {
  const [level, setLevel] = useState("writes");
  if (runCount < 2) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-4 rounded-2xl border border-primary/20 bg-primary/[0.04]"
    >
      <div className="flex items-start gap-2.5">
        <ShieldCheck className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium">
            You've successfully run this workflow {runCount} times
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            How much should AURA handle on its own from here?
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {LEVELS.map((opt) => {
          const Icon = opt.icon;
          const active = level === opt.value;
          return (
            <button
              key={opt.value}
              onClick={() => setLevel(opt.value)}
              className={`w-full text-left flex items-start gap-3 p-3 rounded-xl border transition-colors ${
                active ? `${opt.ring} ${opt.bg}` : "border-white/6 bg-card/30 hover:bg-card/50"
              }`}
            >
              <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${active ? opt.color : "text-muted-foreground"}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium">{opt.title}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/5 text-muted-foreground/70 border border-white/8">
                    {opt.badge}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{opt.desc}</p>
              </div>
              <span
                className={`mt-1 w-4 h-4 rounded-full border flex-shrink-0 flex items-center justify-center ${
                  active ? `${opt.ring} ${opt.bg}` : "border-white/15"
                }`}
              >
                {active && <span className={`w-2 h-2 rounded-full ${opt.color} bg-current`} />}
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between gap-2 mt-3">
        <p className="text-[10px] text-muted-foreground/50 flex items-center gap-1">
          <Shield className="w-3 h-3" />
          Demo concept — change this for any recurring workflow.
        </p>
        <button
          onClick={() => onConfirm?.(level)}
          className="flex items-center gap-1.5 text-xs px-3.5 py-2 rounded-lg bg-gradient-to-r from-primary to-accent text-white font-medium"
        >
          {actionLabel}
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </motion.div>
  );
}