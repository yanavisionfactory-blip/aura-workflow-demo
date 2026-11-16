// The key stays in this form and the authenticated request, never in browser storage.
export function desktopEstimatingDialog(submit, session, signal) {
  return new Promise((resolve, reject) => {
    const dialog = document.createElement("dialog");
    dialog.className = "rounded-2xl border border-white/15 bg-[#151421] p-6 text-white shadow-2xl backdrop:bg-black/70 w-[min(92vw,480px)]";
    dialog.setAttribute("aria-labelledby", "aura-desktop-title");
    dialog.innerHTML = `<form class="space-y-4">
      <h2 id="aura-desktop-title" class="text-lg font-semibold">Connect your Windows workstation</h2>
      <p class="text-sm text-white/70">Run the AURA connector on the Windows computer with PlanSwift and Excel. Use the same connector for both apps. Your drawings stay in PlanSwift; approved quantities and rates are read into this workflow.</p>
      <a class="block text-sm text-violet-300 underline" href="${import.meta.env?.BASE_URL || "/"}downloads/aura-desktop-estimating.zip" download>Download Windows connector and setup guide</a>
      <label class="block text-sm">Connector HTTPS address<input name="endpoint" type="url" required autocomplete="off" placeholder="https://your-workstation.example.com" class="mt-1 block w-full rounded-lg border border-white/20 bg-black/25 p-3"></label>
      <label class="block text-sm">Connection key<input name="connection_key" type="password" required minlength="32" maxlength="256" autocomplete="off" class="mt-1 block w-full rounded-lg border border-white/20 bg-black/25 p-3"></label>
      <p class="text-xs text-white/60">Open PlanSwift and Excel first. AURA verifies the installed application and encrypts the connection key. Keep the connector running while using these tools.</p>
      <p role="alert" class="text-sm text-red-300" hidden></p>
      <div class="flex justify-end gap-3"><button type="button" class="rounded-lg border border-white/20 px-4 py-2">Cancel</button><button type="submit" class="rounded-lg bg-violet-500 px-4 py-2 font-medium">Connect and verify</button></div>
    </form>`;
    const form = dialog.querySelector("form");
    const cancel = dialog.querySelector('button[type="button"]');
    const button = dialog.querySelector('button[type="submit"]');
    const error = dialog.querySelector('[role="alert"]');
    let pending = false;
    let closed = false;
    const cleanup = () => { closed = true; form.reset(); dialog.remove(); signal?.removeEventListener("abort", abort); };
    const abort = () => { cleanup(); reject(new Error("Desktop connection cancelled. Your workflow remains saved.")); };
    cancel.addEventListener("click", () => { if (!pending) abort(); });
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); if (!pending) abort(); });
    signal?.addEventListener("abort", abort, { once: true });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (pending || closed) return;
      pending = true;
      button.disabled = cancel.disabled = true;
      button.textContent = "Checking workstation…";
      error.hidden = true;
      let payload = Object.fromEntries(new FormData(form));
      form.elements.connection_key.value = "";
      try {
        const result = await submit({ ...payload, provider: session.provider, connection_id: session.connection_id || null });
        if (!closed) { cleanup(); resolve(result); }
      } catch (cause) {
        if (!closed) { error.textContent = cause.message || "The workstation could not be verified."; error.hidden = false; }
      } finally {
        payload = null;
        pending = false;
        button.disabled = cancel.disabled = false;
        button.textContent = "Connect and verify";
      }
    });
    if (signal?.aborted) { abort(); return; }
    document.body.append(dialog);
    dialog.showModal();
  });
}
