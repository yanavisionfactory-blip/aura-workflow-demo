// Account names are provider data: always insert them as text, never HTML.
// OAuth credentials and customer-number text inputs do not belong in this dialog.
export function googleAdsAccountDialog({ load, save, selected = null, platform = "Google" }) {
  // Only fixed product labels enter the static template, never provider data.
  platform = platform === "Reddit" ? "Reddit" : "Google";
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "rounded-2xl border border-white/15 bg-[#151421] p-6 text-white shadow-2xl backdrop:bg-black/70 w-[min(92vw,480px)]";
    dialog.setAttribute("aria-labelledby", "aura-ads-title");
    dialog.innerHTML = `
      <form class="space-y-4">
        <h2 id="aura-ads-title" class="text-lg font-semibold">Choose your ${platform} Ads account</h2>
        <p class="text-sm text-white/70">${platform} sign-in is saved. Choose the advertising account AURA should use for new workflows.</p>
        <label data-access class="text-sm" hidden>Account access<select name="access" class="mt-1 block w-full rounded-lg border border-white/20 bg-[#151421] p-3"></select></label>
        <label class="block text-sm">Find an account by name<input name="search" type="search" autocomplete="off" maxlength="100" placeholder="Search your ad accounts" class="mt-1 block w-full rounded-lg border border-white/20 bg-black/25 p-3"></label>
        <label class="block text-sm">Advertising account<select name="account" required class="mt-1 block w-full rounded-lg border border-white/20 bg-[#151421] p-3"></select></label>
        <p data-status role="status" class="text-sm text-white/70"></p>
        <p role="alert" class="text-sm text-red-300" hidden></p>
        <p data-coverage class="text-xs text-amber-200" hidden></p>
        <p class="text-xs text-white/60">${platform === "Reddit" ? "AURA checks every accessible business, including the business directory for accounts shared into a business. Missing access is shown separately." : "Manager accounts show the advertising accounts they can access. Search by name if your account is not listed."} You can change this choice in Manage. Existing reviewed workflows keep their original account.</p>
        <div class="flex flex-wrap justify-end gap-3">
          <button data-retry type="button" class="rounded-lg border border-white/20 px-4 py-2">Refresh</button>
          <button data-close type="button" class="rounded-lg border border-white/20 px-4 py-2">Choose later</button>
          <button type="submit" class="rounded-lg bg-violet-500 px-4 py-2 font-medium disabled:opacity-40" disabled>Use this account</button>
        </div>
      </form>`;
    const form = dialog.querySelector("form");
    const access = form.elements.access;
    const account = form.elements.account;
    const search = form.elements.search;
    const accessLabel = dialog.querySelector("[data-access]");
    const status = dialog.querySelector("[data-status]");
    const error = dialog.querySelector('[role="alert"]');
    const submit = dialog.querySelector('[type="submit"]');
    const closeButton = dialog.querySelector("[data-close]");
    const retry = dialog.querySelector("[data-retry]");
    const coverage = dialog.querySelector("[data-coverage]");
    let login = platform === "Reddit" ? "" : selected?.login_customer_id || "";
    let accounts = [], requestId = 0, timer, closed = false, saving = false, loading = true;
    const option = (value, label) => {
      const element = document.createElement("option");
      element.value = value;
      element.textContent = label;
      return element;
    };
    const clearAccounts = () => {
      accounts = [];
      account.replaceChildren(option("", "Choose an account"));
      account.disabled = submit.disabled = true;
    };
    const close = (value = null) => {
      if (saving) return;
      closed = true;
      requestId += 1;
      window.clearTimeout(timer);
      dialog.close();
      dialog.remove();
      resolve(value);
    };
    const refresh = async (id = ++requestId) => {
      window.clearTimeout(timer);
      clearAccounts();
      loading = true;
      error.hidden = true;
      coverage.hidden = true;
      status.textContent = `Loading your ${platform} Ads accounts…`;
      try {
        const result = await load(login, search.value.trim());
        if (closed || id !== requestId) return;
        access.replaceChildren(option("", platform === "Reddit" ? "All accessible businesses" : "Choose an account or manager"),
          ...result.access_accounts.map((root) => option(root.id, `${root.name} · ${root.id}`)));
        login = result.login_customer_id || "";
        access.value = login;
        accessLabel.hidden = result.access_accounts.length <= 1;
        accounts = result.accounts;
        const warnings = result.coverage?.warnings || [];
        coverage.textContent = warnings.join(" ");
        coverage.hidden = warnings.length === 0;
        account.replaceChildren(option("", "Choose an account"),
          ...accounts.map((row) => option(row.customer_id, `${row.name} · ${row.customer_id}`)));
        // A single option is still confirmed by the customer with Use this account.
        account.value = accounts.find((row) => row.customer_id === selected?.customer_id)?.customer_id
          || (accounts.length === 1 ? accounts[0].customer_id : "");
        account.disabled = !accounts.length;
        submit.disabled = !account.value;
        status.textContent = !result.access_accounts.length
          ? `No ${platform} Ads accounts are available to this ${platform} login. Use Manage → Reconnect to sign in with another ${platform} account.`
          : !login && platform !== "Reddit" ? "Choose the account or manager you use to access Google Ads."
          : !accounts.length ? "No advertising accounts found. Search by account name or choose another account manager."
          : `${accounts.length} advertising account${accounts.length === 1 ? "" : "s"} available.`;
      } catch (cause) {
        if (closed || id !== requestId) return;
        status.textContent = `Your ${platform} sign-in is saved.`;
        error.textContent = cause.message || "Accounts could not be loaded. Try Refresh.";
        error.hidden = false;
        // A revoked manager selection can be recovered by refreshing roots.
        login = "";
      } finally {
        if (!closed && id === requestId) loading = false;
      }
    };
    access.addEventListener("change", () => { login = access.value; search.value = ""; refresh(); });
    account.addEventListener("change", () => { submit.disabled = loading || !account.value; });
    search.addEventListener("input", () => {
      const id = ++requestId;
      clearAccounts();
      loading = true;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => refresh(id), 300);
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); refresh(); }
    });
    retry.addEventListener("click", () => refresh());
    closeButton.addEventListener("click", () => close());
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const chosen = accounts.find((row) => row.customer_id === account.value);
      if (saving || loading || !chosen) return;
      saving = true;
      for (const field of [access, account, search, submit, closeButton, retry]) field.disabled = true;
      error.hidden = true;
      status.textContent = "Confirming account access…";
      try {
        const result = await save({ login_customer_id: chosen.login_customer_id,
          customer_id: chosen.customer_id, search: search.value.trim() });
        saving = false;
        close(result.selected_account);
      } catch (cause) {
        error.textContent = cause.message || "The account could not be selected. Try Refresh.";
        error.hidden = false;
        status.textContent = "Your previous account choice has not changed.";
        saving = false;
        for (const field of [access, account, search, submit, closeButton, retry]) field.disabled = false;
      }
    });
    document.body.append(dialog);
    dialog.showModal();
    refresh();
  });
}
