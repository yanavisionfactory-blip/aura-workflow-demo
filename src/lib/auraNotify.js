// Smart notifications: ping only for long-running completions and errors.
// Quick successful tasks stay silent to avoid noise.

const LONG_STEP_THRESHOLD = 4;
const LONG_DURATION_THRESHOLD = 6; // seconds

export function requestNotifyPermission() {
  if (typeof Notification === "undefined") return;
  if (Notification.permission === "default") {
    try {
      Notification.requestPermission();
    } catch (e) {
      /* ignore */
    }
  }
}

export function notifyWorkflowComplete(title, durationSec, stepCount) {
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  // Suppress notifications for quick tasks
  if (stepCount < LONG_STEP_THRESHOLD && durationSec < LONG_DURATION_THRESHOLD) return;
  try {
    new Notification("AURA finished your workflow", {
      body: `${title} is done${durationSec ? ` · ${Math.round(durationSec)}s` : ""}.`,
    });
  } catch (e) {
    /* ignore */
  }
}

export function notifyWorkflowError(title, reason) {
  if (typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  try {
    new Notification("AURA needs your attention", {
      body: `${title}${reason ? ` — ${reason}` : ""}. Tap to review and fix.`,
    });
  } catch (e) {
    /* ignore */
  }
}