export const sheetEditSchema = {
  type: "object", additionalProperties: false, required: ["changes", "summary"],
  properties: {
    summary: { type: "string" },
    changes: { type: "array", items: {
      type: "object", additionalProperties: false, required: ["row", "column", "value"],
      properties: { row: { type: "integer", minimum: 0 }, column: { type: "integer", minimum: 0 },
        value: { type: ["string", "number", "boolean", "null"] } },
    } },
  },
};

// A model can suggest cells; it cannot redirect the approved destination or
// replace the table shape. Unmentioned cells remain byte-for-byte unchanged.
export function applySheetEdits(args, suggestion) {
  if (!Array.isArray(args.values) || !Array.isArray(suggestion?.changes)
    || typeof suggestion.summary !== "string") throw new Error("AURA returned an incomplete edit. Your draft is unchanged.");
  const values = args.values.map((row) => [...row]);
  const seen = new Set();
  for (const change of suggestion.changes) {
    const { row, column, value } = change || {};
    if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || column < 0
      || row >= values.length || column >= values[row].length
      || (value !== null && !["string", "number", "boolean"].includes(typeof value))
      || (typeof value === "number" && !Number.isFinite(value))
      || seen.has(`${row}:${column}`)) throw new Error("AURA returned an invalid cell edit. Your draft is unchanged.");
    if (typeof value === "string" && /^\s*=/.test(value) && value !== args.values[row][column]) {
      throw new Error("AURA can revise cell text here. Enter formulas manually if you need them.");
    }
    seen.add(`${row}:${column}`);
    values[row][column] = value;
  }
  return { ...args, values };
}

export function sheetComparisonMarkdown(headers, rows) {
  const width = Math.max(headers.length, ...rows.map((row) => row.length), 0);
  if (!width) return "";
  const cell = (value) => String(value ?? "").replace(/\\/g, "\\\\").replace(/\|/g, "\\|")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/[\r\n]+/g, " ");
  const line = (row) => `| ${Array.from({ length: width }, (_, c) => cell(row[c])).join(" | ")} |`;
  return [line(headers), line(Array(width).fill("---")), ...rows.map(line)].join("\n");
}
