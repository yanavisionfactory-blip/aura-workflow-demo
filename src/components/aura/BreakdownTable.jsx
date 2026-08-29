import { motion } from "framer-motion";

// Renders a per-row breakdown (e.g. results by campaign) from the results payload.
export default function BreakdownTable({ breakdown }) {
  if (!breakdown || !breakdown.columns) return null;
  const { columns, rows = [], footnote } = breakdown;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-white/6 bg-card/40 overflow-hidden"
    >
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/8 bg-secondary/30">
              {columns.map((c, i) => (
                <th key={i} className="text-left font-medium text-muted-foreground px-3 py-2 whitespace-nowrap">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className="border-b border-white/4 last:border-0">
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className={`px-3 py-2 whitespace-nowrap ${ci === 0 ? "font-medium" : "text-muted-foreground"}`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {footnote && (
        <p className="text-[10px] text-muted-foreground/50 px-3 py-2 border-t border-white/4">{footnote}</p>
      )}
    </motion.div>
  );
}