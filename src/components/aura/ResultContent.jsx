import ReactMarkdown from "react-markdown";

const tableDivider = (line = "") => {
  const cells = line.replace(/^\s*\||\|\s*$/g, "").split("|");
  return cells.length > 1 && cells.every((cell) => /^\s*:?-{3,}:?\s*$/.test(cell));
};

const tableCells = (line = "") => line
  .replace(/^\s*\||\|\s*$/g, "")
  .split("|")
  .map((cell) => cell.trim());

export function resultContentBlocks(content = "") {
  const lines = String(content).replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let markdown = [];
  const flushMarkdown = () => {
    const value = markdown.join("\n").trim();
    if (value) blocks.push({ type: "markdown", value });
    markdown = [];
  };

  for (let index = 0; index < lines.length; index += 1) {
    if (lines[index].includes("|") && tableDivider(lines[index + 1])) {
      flushMarkdown();
      const headers = tableCells(lines[index]);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      index -= 1;
      blocks.push({ type: "table", headers, rows });
      continue;
    }
    markdown.push(lines[index]);
  }
  flushMarkdown();
  return blocks;
}

const markdownComponents = {
  h1: ({ children }) => <h4 className="mb-2 mt-5 text-base font-semibold first:mt-0">{children}</h4>,
  h2: ({ children }) => <h4 className="mb-2 mt-5 text-base font-semibold first:mt-0">{children}</h4>,
  h3: ({ children }) => <h5 className="mb-1.5 mt-4 text-sm font-semibold first:mt-0">{children}</h5>,
  p: ({ children }) => <p className="my-2 text-sm leading-6 text-foreground/80 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 text-sm leading-6 text-foreground/80">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5 text-sm leading-6 text-foreground/80">{children}</ol>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium text-primary underline decoration-primary/30 underline-offset-2 hover:decoration-primary">
      {children}
    </a>
  ),
};

export default function ResultContent({ content }) {
  const blocks = resultContentBlocks(content);
  return (
    <div className="min-w-0">
      {blocks.map((block, blockIndex) => block.type === "table" ? (
        <div key={`table-${blockIndex}`} className="my-4 overflow-x-auto rounded-xl border border-white/[0.08] bg-[#080d19]/55 first:mt-0 last:mb-0">
          <table className="w-full min-w-[32rem] text-left text-xs">
            <thead className="border-b border-white/[0.08] bg-white/[0.035]">
              <tr>
                {block.headers.map((header, index) => (
                  <th key={index} className="px-3.5 py-3 font-semibold text-foreground/85">{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-b border-white/[0.055] last:border-0">
                  {block.headers.map((_, cellIndex) => (
                    <td key={cellIndex} className={`px-3.5 py-3 align-top leading-5 ${cellIndex === 0 ? "font-medium text-foreground" : "text-foreground/70"}`}>
                      <ReactMarkdown components={markdownComponents}>{row[cellIndex] || ""}</ReactMarkdown>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ReactMarkdown key={`markdown-${blockIndex}`} components={markdownComponents}>{block.value}</ReactMarkdown>
      ))}
    </div>
  );
}
