// Shared component, independent app authorization. Grants stay in memory and expire.
const APPS = {
  planswift: { name: "PlanSwift", permissions: "Read existing PlanSwift measurements." },
  "excel-desktop": { name: "Microsoft Excel (Desktop)", permissions: "Read approved Excel rate books; create and download new Excel estimates." },
};
export function desktopPairingDialog(api, session, signal, { waitMs = 120000, pollMs = 2000 } = {}) {
  return new Promise((resolve, reject) => {
    const app = APPS[session.provider];
    if (!app) { reject(new Error("Select the app you want to connect.")); return; }
    const dialog = document.createElement("dialog");
    dialog.className = "rounded-2xl border border-white/15 bg-[#151421] p-6 text-white shadow-2xl backdrop:bg-black/70 w-[min(92vw,480px)]";
    dialog.setAttribute("aria-labelledby", "aura-computer-title");
    dialog.innerHTML = `<div class="space-y-4">
      <h2 id="aura-computer-title" class="text-lg font-semibold">Connect ${app.name}</h2>
      <p class="text-sm text-white/70">Approve access to ${app.name} on your Windows computer. This connects only this app.</p>
      <p class="text-xs text-white/60">Access: ${app.permissions}</p>
      <a class="block text-sm text-violet-300 underline" href="${import.meta.env?.BASE_URL || "/"}downloads/AURA-Desktop.exe" download>Install AURA Desktop for Windows</a>
      <p class="text-xs text-white/60">Install once. No API key or network setup is needed. Keep the desktop app open while AURA works.</p>
      <p data-status role="status" aria-live="polite" class="text-sm">Preparing authorization…</p>
      <p data-error role="alert" class="text-sm text-red-300" hidden></p>
      <a data-open class="block rounded-lg bg-violet-500 px-4 py-3 text-center font-medium" hidden>Open AURA Desktop</a>
      <button data-copy type="button" class="text-sm text-white/70 underline" hidden>Copy pairing code instead</button>
      <div class="flex justify-end gap-3"><button data-cancel type="button" class="rounded-lg border border-white/20 px-4 py-2">Cancel</button><button data-retry type="button" class="rounded-lg bg-violet-500 px-4 py-2" hidden>Try again</button></div>
    </div>`;
    const status = dialog.querySelector("[data-status]");
    const error = dialog.querySelector("[data-error]");
    const open = dialog.querySelector("[data-open]");
    const copy = dialog.querySelector("[data-copy]");
    const retry = dialog.querySelector("[data-retry]");
    let closed = false, grant = null, controller = null, timer = null, deadlineTimer = null;
    const cancelGrant = () => {
      const id = grant?.pairing_id;
      grant = null;
      if (id) Promise.resolve(api.cancel(id)).catch(() => {});
    };
    const stopAttempt = () => {
      clearTimeout(timer); clearTimeout(deadlineTimer); controller?.abort();
      open.hidden = copy.hidden = true; open.removeAttribute("href");
    };
    const cleanup = () => {
      closed = true; stopAttempt(); grant = null; dialog.remove();
      signal?.removeEventListener("abort", abort);
    };
    const abort = () => {
      if (closed) return;
      cancelGrant(); cleanup(); reject(new Error("Connection window closed. Your workflow remains saved."));
    };
    const failed = (message) => {
      if (closed) return;
      stopAttempt(); cancelGrant();
      status.textContent = "Connection not verified yet.";
      error.textContent = message; error.hidden = false; retry.hidden = false;
    };
    const start = async () => {
      stopAttempt(); cancelGrant();
      controller = new AbortController();
      const attempt = controller;
      retry.hidden = error.hidden = true;
      status.textContent = "Preparing authorization…";
      const until = Date.now() + waitMs;
      deadlineTimer = setTimeout(() => failed("No response from the Windows helper within two minutes. Install or open AURA Desktop on that computer, then try again."), waitMs);
      try {
        const created = await api.start(attempt.signal);
        if (closed || attempt.signal.aborted) {
          if (created?.pairing_id) Promise.resolve(api.cancel(created.pairing_id)).catch(() => {});
          return;
        }
        grant = created;
        if (grant.provider !== session.provider) throw new Error("The connection request does not match this app. Try again.");
        open.href = "aura-estimator://pair?code=" + encodeURIComponent(grant.code);
        open.hidden = copy.hidden = false;
        const poll = async () => {
          try {
            const current = await api.status(grant.pairing_id, attempt.signal);
            if (closed || attempt.signal.aborted) return;
            if (["revoked", "cancelled", "expired"].includes(current.status)) {
              throw new Error(current.message || "This authorization expired. Try again.");
            }
            if (current.status === "verified") {
              const connection = current.connections?.find((item) => item.provider === session.provider);
              if (!connection?.id || current.connections.length !== 1) throw new Error("The requested app was not verified separately. Retry the connection.");
              cleanup(); resolve({ id: connection.id, status: "verified", connections: current.connections });
              return;
            }
            const remaining = Math.max(0, Math.ceil((until - Date.now()) / 1000));
            status.textContent = current.message || `Waiting for approval to connect ${app.name}. Open AURA Desktop on your Windows computer. ${remaining}s remaining.`;
            timer = setTimeout(poll, pollMs);
          } catch (cause) {
            if (!attempt.signal.aborted && !closed) failed(cause.message || "The connection check failed. Try again.");
          }
        };
        await poll();
      } catch (cause) {
        if (!attempt.signal.aborted && !closed) failed(cause.message || "Could not start authorization. Try again.");
      }
    };
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(grant.code);
        status.textContent = "Pairing code copied. Paste it into AURA Desktop on your Windows computer.";
      } catch {
        status.textContent = "Clipboard is unavailable. Use Open AURA Desktop on your Windows computer.";
      }
    });
    retry.addEventListener("click", start);
    dialog.querySelector("[data-cancel]").addEventListener("click", abort);
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); abort(); });
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) { abort(); return; }
    document.body.append(dialog); dialog.showModal(); start();
  });
}
