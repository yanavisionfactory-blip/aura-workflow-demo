// Present full saved campaign sections without inventing copy or execution.
export function campaignCopySections(body) {
  if (typeof body !== "string") return null;
  const sections = [...body.matchAll(/^## ([^\n]+)\n([\s\S]*?)(?=^## |$(?![\s\S]))/gm)]
    .map((match) => ({ title: match[1], body: match[2].trim() }));
  const groups = [["Google Search", /^Google Search concept [12]$/, 2],
    ["Social", /^Platform-neutral social concept [123]$/, 3],
    ["Business Profile", /^Optional Business Profile post$/, 1],
    ["Indoor screens", /^Indoor-screen copy concept [123]$/, 3]]
    .map(([name, pattern, count]) => ({ name, expected: count, sections: sections.filter((s) => pattern.test(s.title)) }));
  return groups.every((g) => g.sections.length === g.expected && g.sections.every((s) => s.body.length > 60)) ? groups : null;
}
