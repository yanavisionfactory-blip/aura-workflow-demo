import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, CalendarClock, Check, Bell, BellOff, ShieldAlert, Eye, FileCheck2, Zap } from "lucide-react";
import { aura } from "@/api/auraClient";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const CADENCES = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
];

function computeNextRun(cadence, dayOfWeek, dayOfMonth, time) {
  const [h, m] = time.split(":").map(Number);
  const now = new Date();
  let next = new Date(now);
  next.setHours(h, m, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  if (cadence === "weekly") {
    while (next.getDay() !== dayOfWeek) next.setDate(next.getDate() + 1);
  } else if (cadence === "monthly") {
    next.setDate(dayOfMonth);
    next.setHours(h, m, 0, 0);
    if (next <= now) next.setMonth(next.getMonth() + 1);
  }
  return next.toISOString();
}

const APPROVAL_LEVELS = [
  { value: "review", icon: Eye, label: "Review every run" },
  { value: "writes", icon: FileCheck2, label: "Ask before sending/changing anything" },
  { value: "auto", icon: Zap, label: "Run automatically" },
];

export default function ScheduleModal({ open, onClose, prompt, title }) {
  const [cadence, setCadence] = useState("weekly");
  const [dayOfWeek, setDayOfWeek] = useState(1);
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [time, setTime] = useState("08:00");
  const [notifyCompleted, setNotifyCompleted] = useState(true);
  const [notifyErrors, setNotifyErrors] = useState(true);
  const [approval, setApproval] = useState("writes");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (open) {
      setSaved(false);
      setCadence("weekly");
      setDayOfWeek(1);
      setDayOfMonth(1);
      setTime("08:00");
      setNotifyCompleted(true);
      setNotifyErrors(true);
      setApproval("writes");
    }
  }, [open]);

  const nextRun = computeNextRun(cadence, dayOfWeek, dayOfMonth, time);
  const nextLabel = new Date(nextRun).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

  const summary =
    cadence === "daily"
      ? `every day at ${time}`
      : cadence === "weekly"
      ? `every ${DAYS[dayOfWeek]} at ${time}`
      : `on day ${dayOfMonth} of each month at ${time}`;

  const handleSave = async () => {
    setSaving(true);
    try {
      await aura.entities.Schedule.create({
        prompt: prompt || "",
        title: title || "Scheduled workflow",
        cadence,
        day_of_week: cadence === "weekly" ? dayOfWeek : null,
        day_of_month: cadence === "monthly" ? dayOfMonth : null,
        time,
        enabled: true,
        next_run: nextRun,
      });
      setSaved(true);
    } catch (e) {
      /* ignore */
    }
    setSaving(false);
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
            className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 16 }}
            transition={{ type: "spring", stiffness: 260, damping: 24 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
          >
            <div className="w-full max-w-md bg-card border border-white/10 rounded-2xl shadow-2xl pointer-events-auto overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-4 border-b border-white/6">
                <CalendarClock className="w-4 h-4 text-primary" />
                <h3 className="text-sm font-semibold">Schedule this workflow</h3>
                <button
                  onClick={onClose}
                  className="ml-auto p-1.5 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-foreground transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {saved ? (
                <div className="p-6 text-center">
                  <div className="inline-flex p-3 rounded-2xl bg-emerald-400/10 border border-emerald-400/20 mb-3">
                    <Check className="w-6 h-6 text-emerald-400" />
                  </div>
                  <p className="text-sm font-medium">Scheduled — running {summary}</p>
                  <p className="text-xs text-muted-foreground mt-1">First run {nextLabel}.</p>
                  <button
                    onClick={onClose}
                    className="mt-4 text-xs px-4 py-2 rounded-lg bg-primary text-primary-foreground"
                  >
                    Done
                  </button>
                </div>
              ) : (
                <div className="p-5 space-y-4">
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Repeat</label>
                    <div className="flex gap-1.5 mt-1.5">
                      {CADENCES.map((c) => (
                        <button
                          key={c.value}
                          onClick={() => setCadence(c.value)}
                          className={`flex-1 text-xs py-2 rounded-lg border transition-colors ${
                            cadence === c.value
                              ? "border-primary/40 bg-primary/15 text-primary"
                              : "border-white/8 text-muted-foreground hover:bg-white/5"
                          }`}
                        >
                          {c.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {cadence === "weekly" && (
                    <div>
                      <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60">On</label>
                      <div className="grid grid-cols-7 gap-1 mt-1.5">
                        {DAYS.map((d, i) => (
                          <button
                            key={i}
                            onClick={() => setDayOfWeek(i)}
                            className={`text-[10px] py-1.5 rounded-lg border transition-colors ${
                              dayOfWeek === i
                                ? "border-primary/40 bg-primary/15 text-primary"
                                : "border-white/8 text-muted-foreground hover:bg-white/5"
                            }`}
                          >
                            {d.slice(0, 1)}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {cadence === "monthly" && (
                    <div>
                      <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Day of month</label>
                      <input
                        type="number"
                        min={1}
                        max={31}
                        value={dayOfMonth}
                        onChange={(e) => setDayOfMonth(Math.min(31, Math.max(1, Number(e.target.value) || 1)))}
                        className="w-full mt-1.5 bg-secondary/40 border border-white/8 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40"
                      />
                    </div>
                  )}

                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60">At</label>
                    <input
                      type="time"
                      value={time}
                      onChange={(e) => setTime(e.target.value)}
                      className="w-full mt-1.5 bg-secondary/40 border border-white/8 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary/40"
                    />
                  </div>

                  {/* Notify me */}
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60 flex items-center gap-1.5">
                      <Bell className="w-3 h-3" /> Notify me
                    </label>
                    <div className="mt-1.5 space-y-1.5">
                      <button
                        onClick={() => setNotifyCompleted((v) => !v)}
                        className="w-full flex items-center gap-2.5 p-2.5 rounded-lg border border-white/8 bg-card/30 hover:bg-card/50 transition-colors"
                      >
                        <span className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${notifyCompleted ? "bg-primary border-primary" : "border-white/15"}`}>
                          {notifyCompleted && <Check className="w-3 h-3 text-primary-foreground" />}
                        </span>
                        <span className="text-xs">When completed</span>
                      </button>
                      <button
                        onClick={() => setNotifyErrors((v) => !v)}
                        className="w-full flex items-center gap-2.5 p-2.5 rounded-lg border border-white/8 bg-card/30 hover:bg-card/50 transition-colors"
                      >
                        <span className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${notifyErrors ? "bg-primary border-primary" : "border-white/15"}`}>
                          {notifyErrors && <Check className="w-3 h-3 text-primary-foreground" />}
                        </span>
                        <span className="text-xs">Immediately if something needs attention</span>
                      </button>
                    </div>
                    {!notifyCompleted && !notifyErrors && (
                      <p className="text-[10px] text-muted-foreground/50 mt-1.5 flex items-center gap-1">
                        <BellOff className="w-3 h-3" /> You'll only hear from AURA when you open the app.
                      </p>
                    )}
                  </div>

                  {/* Approval */}
                  <div>
                    <label className="text-[10px] uppercase tracking-wider text-muted-foreground/60 flex items-center gap-1.5">
                      <ShieldAlert className="w-3 h-3" /> Approval
                    </label>
                    <div className="mt-1.5 space-y-1.5">
                      {APPROVAL_LEVELS.map((opt) => {
                        const Icon = opt.icon;
                        const active = approval === opt.value;
                        return (
                          <button
                            key={opt.value}
                            onClick={() => setApproval(opt.value)}
                            className={`w-full flex items-center gap-2.5 p-2.5 rounded-lg border transition-colors text-left ${
                              active ? "border-primary/40 bg-primary/10" : "border-white/8 bg-card/30 hover:bg-card/50"
                            }`}
                          >
                            <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${active ? "text-primary" : "text-muted-foreground"}`} />
                            <span className={`text-xs ${active ? "text-primary font-medium" : ""}`}>{opt.label}</span>
                            <span className={`ml-auto w-3.5 h-3.5 rounded-full border flex-shrink-0 flex items-center justify-center ${active ? "border-primary bg-primary" : "border-white/15"}`}>
                              {active && <span className="w-1.5 h-1.5 rounded-full bg-primary-foreground" />}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="p-3 rounded-xl bg-primary/5 border border-primary/15">
                    <p className="text-xs">
                      Runs <span className="text-primary font-medium">{summary}</span>
                    </p>
                    <p className="text-[11px] text-muted-foreground mt-1">First run {nextLabel}</p>
                  </div>

                  <div className="flex justify-end gap-2 pt-1">
                    <button
                      onClick={onClose}
                      className="text-xs px-3 py-2 rounded-lg border border-white/10 text-muted-foreground hover:bg-white/5"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleSave}
                      disabled={saving}
                      className="text-xs px-4 py-2 rounded-lg bg-gradient-to-r from-primary to-accent text-white font-medium disabled:opacity-50"
                    >
                      {saving ? "Saving…" : "Save & schedule"}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
