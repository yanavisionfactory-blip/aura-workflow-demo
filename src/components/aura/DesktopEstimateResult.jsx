import { useState } from "react";
import { Download, FileSpreadsheet, Loader2 } from "lucide-react";
import { downloadDesktopEstimate } from "@/lib/auraApi";

export default function DesktopEstimateResult({ receipt }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function download() {
    setBusy(true); setError("");
    try { await downloadDesktopEstimate(receipt.report_id); }
    catch (cause) { setError(cause.message || "The workbook is unavailable."); }
    finally { setBusy(false); }
  }
  return <section aria-label="Excel estimate" className="rounded-2xl border border-white/10 bg-card p-6 space-y-5">
    <div className="flex items-center gap-3"><FileSpreadsheet className="h-7 w-7 text-emerald-400"/><div><h3 className="font-semibold">Draft construction estimate</h3><p className="text-sm text-muted-foreground">Created and recalculated in Microsoft Excel</p></div></div>
    <div className="flex flex-wrap gap-8"><div><p className="text-xs text-muted-foreground">Estimated total</p><p className="text-2xl font-semibold">{new Intl.NumberFormat(undefined, { style: "currency", currency: receipt.currency }).format(receipt.total)}</p></div><div><p className="text-xs text-muted-foreground">Takeoff rows</p><p className="text-2xl font-semibold">{receipt.row_count}</p></div></div>
    <p className="text-sm text-muted-foreground">The workbook contains the source quantities, approved rates, formulas and cost summary. Review scope, drawing scale and exclusions before accepting the estimate.</p>
    <button type="button" onClick={download} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin"/> : <Download className="h-4 w-4"/>}{busy ? "Verifying workbook…" : "Download Excel estimate"}</button>
    <p className="text-xs text-muted-foreground">Keep the connected Windows workstation online for download.</p>
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </section>;
}
