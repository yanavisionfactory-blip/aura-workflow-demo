import { getAttachedDocuments } from "@/lib/documentStore";
import { uploadBatchError } from "@/lib/uploadLimits.mjs";

export function takeoffImportDialog(preview, signal) {
  return new Promise((resolve, reject) => {
    const dialog = document.createElement("dialog");
    dialog.className = "rounded-2xl border border-white/15 bg-[#151421] p-6 text-white shadow-2xl backdrop:bg-black/70 w-[min(92vw,500px)] max-h-[90dvh] overflow-y-auto [&_[hidden]]:!hidden";
    dialog.setAttribute("aria-labelledby", "aura-takeoff-title");
    dialog.innerHTML = `<div class="space-y-4">
      <h2 id="aura-takeoff-title" class="text-xl font-semibold">Use PlanSwift data</h2>
      <p class="text-base text-white/80">Import an Excel or CSV export from PlanSwift. Works in your browser on any device, with no AURA Desktop installation.</p>
      <p class="text-sm text-white/65">Export your takeoff from PlanSwift, then choose the .xlsx or .csv file. Include item names, quantities and units. Connect Excel separately to use an online rate book.</p>
      <label class="block text-sm font-medium" for="aura-takeoff-file">PlanSwift export</label>
      <input id="aura-takeoff-file" type="file" accept=".xlsx,.csv" class="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-violet-500 file:px-4 file:py-2 file:text-white" />
      <p data-status role="status" aria-live="polite" class="text-sm text-white/80">AURA checks the file before adding it to your workflow.</p>
      <p data-error role="alert" class="text-sm text-red-300" hidden></p>
      <button data-import type="button" disabled class="w-full rounded-lg bg-violet-500 px-4 py-3 font-medium disabled:opacity-40">Use this export</button>
      <p class="text-sm text-white/65">This imports a snapshot. It does not connect the installed app or create new measurements. Upload a new export when the takeoff changes.</p>
      <details class="border-t border-white/15 pt-3"><summary class="cursor-pointer text-sm text-white/75">Need access to the installed app?</summary>
        <p class="my-3 text-sm text-white/65">Live access requires PlanSwift and AURA Desktop on Windows.</p>
        <button data-desktop type="button" class="rounded-lg border border-white/25 px-4 py-2 text-sm">Connect installed PlanSwift</button>
      </details>
      <button data-cancel type="button" class="text-sm text-white/75 underline">Cancel</button>
    </div>`;
    const input = dialog.querySelector("input");
    const status = dialog.querySelector("[data-status]");
    const error = dialog.querySelector("[data-error]");
    const submit = dialog.querySelector("[data-import]");
    let closed = false, selected = null, attempt = null, reader = null;
    const cleanup = () => {
      closed = true; attempt?.abort(); reader?.abort(); dialog.remove();
      signal?.removeEventListener("abort", abort);
    };
    const abort = () => { if (!closed) { cleanup(); reject(new Error("Import cancelled. Your workflow is unchanged.")); } };
    const finish = (result) => { if (!closed) { cleanup(); resolve(result); } };
    input.addEventListener("change", async () => {
      attempt?.abort(); reader?.abort(); selected = null; submit.disabled = true; error.hidden = true;
      const current = new AbortController(); attempt = current;
      const file = input.files?.[0];
      if (!file) { status.textContent = "Choose an .xlsx or .csv export."; return; }
      try {
        const limit = uploadBatchError([file], getAttachedDocuments());
        if (limit) throw new Error(limit);
        if (!/\.(xlsx|csv)$/i.test(file.name)) throw new Error("Choose an .xlsx or .csv export.");
        status.textContent = "Checking your export…";
        const file_url = await new Promise((done, fail) => {
          const currentReader = new document.defaultView.FileReader(); reader = currentReader;
          currentReader.onload = () => done(currentReader.result);
          currentReader.onerror = () => fail(new Error("Could not read this file. Choose it again."));
          currentReader.onabort = () => fail(new Error("File reading cancelled."));
          currentReader.readAsDataURL(file);
        });
        if (closed || current.signal.aborted) return;
        const result = await preview({ name: file.name, file_url }, current.signal);
        if (closed || current.signal.aborted) return;
        selected = { name: file.name, file_url, size: file.size, source_app: "planswift", source_kind: "export" };
        status.textContent = `${file.name}: ${result.row_count} rows including headings across ${result.sheets.length} sheet${result.sheets.length === 1 ? "" : "s"}. ${result.warnings.join(" ")}`;
        submit.disabled = false;
      } catch (cause) {
        if (closed || current.signal.aborted) return;
        status.textContent = "No data added."; error.textContent = cause.message || "Could not check this export. Try again."; error.hidden = false;
      }
    });
    submit.addEventListener("click", () => {
      if (!selected) return;
      const limit = uploadBatchError([{ size: selected.size }], getAttachedDocuments());
      if (limit) { error.textContent = limit; error.hidden = false; return; }
      finish({ document: selected });
    });
    dialog.querySelector("[data-desktop]").addEventListener("click", () => finish({ desktop: true }));
    dialog.querySelector("[data-cancel]").addEventListener("click", abort);
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); abort(); });
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) { abort(); return; }
    document.body.append(dialog); dialog.showModal();
  });
}
