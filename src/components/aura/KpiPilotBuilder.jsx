import { useState } from "react";

const defaults = {
  business_name: "Plantéa", reporting_period: "Mason pilot — sample period",
  illustrative: true, currency: "USD", denominator: "sessions",
  target: { revenue: 35000, orders: 500, conversions: 500, denominator_value: 20000 },
  actual: { revenue: 29960, orders: 428, conversions: 428, denominator_value: 21400 },
  product_brief: "Nourishing Serum. Handcrafted/formulated in Texas, USA. Retail $70. Unscented gel. Brief supplied by Mason: hydration, barrier protection and brightening; prickly pear cactus extract, botanical hyaluronic alternatives, soothing plant extracts. These product claims have not been independently verified.",
  feedback: [{ feedback_id: "MASON-QA-001", reviewer: "Pilot test", feedback: "Make the dashboard clean and retain the same conversion denominator." }],
};
const input = "w-full rounded-lg border border-white/15 bg-background p-2 text-sm";

export default function KpiPilotBuilder({ onSubmit, onBack }) {
  const [fields, setFields] = useState(defaults);
  const update = (key, value) => setFields((old) => ({ ...old, [key]: value }));
  return <form onSubmit={(event) => { event.preventDefault(); onSubmit(`AURA_KPI_PILOT_V1\n${JSON.stringify(fields)}`); }} className="mx-auto max-w-2xl space-y-5 rounded-2xl border border-white/10 bg-card p-6">
    <div><h1 className="text-xl font-semibold">KPI dashboard pilot</h1><p className="mt-2 text-sm text-muted-foreground">Create one Google workbook with a KPI dashboard, feedback tab and product brief. AURA checks the saved values and formulas before marking it complete.</p></div>
    <label className="block text-sm">Business name<input required maxLength={100} className={input} value={fields.business_name} onChange={(e) => update("business_name", e.target.value)} /></label>
    <label className="block text-sm">Reporting period<input required maxLength={100} className={input} value={fields.reporting_period} onChange={(e) => update("reporting_period", e.target.value)} /></label>
    <label className="block text-sm">Conversion denominator<select className={input} value={fields.denominator} onChange={(e) => update("denominator", e.target.value)}>{["sessions", "visitors", "leads"].map((name) => <option key={name}>{name}</option>)}</select></label>
    <table className="w-full text-sm"><thead><tr><th className="text-left">Metric</th><th>Target</th><th>Actual</th></tr></thead><tbody>{[["revenue", "Revenue (USD)"], ["orders", "Orders"], ["conversions", "Conversions"], ["denominator_value", fields.denominator]].map(([key, label]) => <tr key={key}><th className="text-left font-normal pr-2">{label}</th>{["target", "actual"].map((side) => <td key={side} className="p-1"><input aria-label={`${side} ${label}`} type="number" required min="0" max={key === "revenue" ? 1e12 : 1e9} step={key === "revenue" ? "0.01" : "1"} className={input} value={fields[side][key]} onChange={(e) => update(side, { ...fields[side], [key]: e.target.value === "" ? "" : Number(e.target.value) })} /></td>)}</tr>)}</tbody></table>
    <p className="text-xs text-muted-foreground">Average order value = revenue ÷ orders. Conversion rate = conversions ÷ the same denominator for target and actual. Zero denominators display “n/a”.</p>
    <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={fields.illustrative} onChange={(e) => update("illustrative", e.target.checked)} />These are illustrative test figures, not real business performance.</label>
    <label className="block text-sm">Product brief<textarea className={input} rows={3} maxLength={4000} value={fields.product_brief} onChange={(e) => update("product_brief", e.target.value)} /></label>
    <label className="block text-sm">Feedback to transfer<textarea required className={input} rows={2} maxLength={2000} value={fields.feedback[0].feedback} onChange={(e) => update("feedback", [{ ...fields.feedback[0], feedback: e.target.value }])} /></label>
    <p className="text-xs text-muted-foreground">Destination: a new workbook in the Google account shown during plan review. This form does not create or share anything.</p>
    <div className="flex justify-between"><button type="button" onClick={onBack}>Back</button><button type="submit" className="rounded-lg bg-primary px-4 py-2 text-white">Review workflow</button></div>
  </form>;
}
