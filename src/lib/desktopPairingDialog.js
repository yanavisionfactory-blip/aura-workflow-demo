// Shared computer authorization; pairing grants stay in memory and expire.
export function desktopPairingDialog(api, session, signal, { waitMs = 120000, pollMs = 2000 } = {}) {
  return new Promise((resolve, reject) => {
    const dialog = document.createElement("dialog");
    dialog.className = "rounded-2xl border border-white/15 bg-[#151421] p-6 text-white shadow-2xl backdrop:bg-black/70 w-[min(92vw,480px)]";
    dialog.setAttribute("aria-labelledby", "aura-computer-title");
    dialog.innerHTML = `<div class="space-y-4">
      <h2 id="aura-computer-title" class="text-lg font-semibold">Connect your computer</h2>
      <p class="text-sm text-white/70">Approve access in AURA Desktop on the Windows computer where your apps are installed. One authorization connects PlanSwift and Excel.</p>
      <p class="text-xs text-white/60">Access: read existing PlanSwift measurements and approved rates; create and download new Excel estimates.</p>
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
      status.textContent = "Not connected yet.";
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
              if (!connection?.id) throw new Error("The requested app was not verified. Retry the connection.");
              cleanup(); resolve({ id: connection.id, status: "verified", connections: current.connections });
              return;
            }
            const remaining = Math.max(0, Math.ceil((until - Date.now()) / 1000));
            status.textContent = current.message || `Waiting for your Windows computer. Open AURA Desktop and approve access. ${remaining}s remaining.`;
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
