import { Eye, FileCheck2, Zap } from "lucide-react";

export const LEVELS = [
  {
    value: "review",
    icon: Eye,
    title: "Review every run",
    desc: "AURA asks you to review the plan before starting.",
    color: "text-amber-300",
    ring: "border-amber-400/40",
    bg: "bg-amber-400/10",
  },
  {
    value: "writes",
    icon: FileCheck2,
    title: "Ask before sending or changing data",
    desc: "AURA can read and prepare automatically, but asks before consequential actions.",
    color: "text-accent",
    ring: "border-accent/40",
    bg: "bg-accent/10",
  },
  {
    value: "auto",
    icon: Zap,
    title: "Run automatically",
    desc: "AURA completes the workflow and only interrupts when something needs attention.",
    color: "text-emerald-300",
    ring: "border-emerald-400/40",
    bg: "bg-emerald-400/10",
  },
];

export const LABELS = {
  review: "Review every run",
  writes: "Ask before sending or changing data",
  auto: "Run automatically",
};