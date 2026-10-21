// Credentials live only in this form and the HTTPS request. Never persist them
// in browser storage, workflow arguments, console output or URL parameters.
export function shopifyCredentialDialog(submit, session) {
  return new Promise((resolve, reject) => {
    const dialog = document.createElement("dialog");
    dialog.className = "rounded-2xl border border-white/15 bg-[#151421] p-6 text-white shadow-2xl backdrop:bg-black/70 w-[min(92vw,440px)]";
    dialog.setAttribute("aria-labelledby", "aura-shopify-title");
    dialog.innerHTML = `
      <form class="space-y-4">
        <h2 id="aura-shopify-title" class="text-lg font-semibold">Connect Shopify</h2>
        <p class="text-sm text-white/70">Connect an installed app from your Shopify organization. AURA verifies the store and granted permissions. This connection reads store identity and content pages. Live pages stay unchanged.</p>
        <label class="block text-sm">Shop ID<input name="shop" type="text" autocomplete="off" required maxlength="100" placeholder="your-store" class="mt-1 block w-full rounded-lg border border-white/20 bg-black/25 p-3"></label>
        <label class="block text-sm">Client ID<input name="client_id" type="text" autocomplete="off" required minlength="10" maxlength="256" class="mt-1 block w-full rounded-lg border border-white/20 bg-black/25 p-3"></label>
        <label class="block text-sm">Client secret<input name="client_secret" type="password" autocomplete="off" required minlength="10" maxlength="512" class="mt-1 block w-full rounded-lg border border-white/20 bg-black/25 p-3"></label>
        <p class="text-xs text-white/60">Credentials are encrypted on AURA's server and used only with Shopify. The secret is cleared from this form after submission.</p>
        <p role="alert" class="text-sm text-red-300" hidden></p>
        <div class="flex justify-end gap-3"><button type="button" class="rounded-lg border border-white/20 px-4 py-2">Cancel</button><button type="submit" class="rounded-lg bg-violet-500 px-4 py-2 font-medium">Connect and verify</button></div>
      </form>`;
    const form = dialog.querySelector("form");
    const cancel = dialog.querySelector('button[type="button"]');
    const submitButton = dialog.querySelector('button[type="submit"]');
    const error = dialog.querySelector('[role="alert"]');
    let pending = false;
    const close = () => {
      if (pending) return;
      form.reset();
      dialog.remove();
      reject(new Error("Shopify connection cancelled. Your workflow remains saved."));
    };
    cancel.addEventListener("click", close);
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (pending) return;
      pending = true;
      submitButton.disabled = cancel.disabled = true;
      submitButton.textContent = "Verifying Shopify…";
      error.hidden = true;
      let payload = Object.fromEntries(new FormData(form));
      form.elements.client_secret.value = "";
      try {
        const result = await submit({ ...payload, connection_id: session.connection_id || null });
        form.reset();
        dialog.remove();
        resolve(result);
      } catch (cause) {
        error.textContent = cause.message || "Shopify could not verify this connection.";
        error.hidden = false;
      } finally {
        payload = null;
        pending = false;
        submitButton.disabled = cancel.disabled = false;
        submitButton.textContent = "Connect and verify";
      }
    });
    document.body.append(dialog);
    dialog.showModal();
  });
}
