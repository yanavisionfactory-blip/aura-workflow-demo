// Navigation over an accepted report body, never an imported execution receipt.
export function campaignReportGroups(body) {
  if (typeof body !== "string") return null;
  const groups = [
    ["Brief", /brief|objective|budget|channel plan|scope|source|execution|consistency/i],
    ["Google Ads", /search|responsive|\brsa\b|keyword|negative/i],
    ["Social ads", /social|facebook|instagram|meta|linkedin/i],
    ["Business Profile", /business profile|\bgbp\b/i],
    ["Indoor screens", /screen|signage/i],
    ["Assets", /asset|creative checklist|rights/i],
    ["Approvals and handoff", /approv|handoff|implementation|measurement|landing|manual/i],
  ].map(([name, pattern]) => ({ name, pattern, sections: [] }));
  const headings = [...body.matchAll(/^## ([^\n]+)\n/gm)];
  if (!headings.length) return null;
  const intro = body.slice(0, headings[0].index).trim();
  headings.forEach((match, index) => {
    const section = { title: match[1].trim(), body: body.slice(match.index,
      headings[index + 1]?.index ?? body.length).trim() };
    // Asset requirements for a channel belong to Assets, not to ad copy.
    const matchGroup = groups.slice(5).find((group) => group.pattern.test(section.title))
      || groups.slice(1, 5).find((group) => group.pattern.test(section.title)) || groups[0];
    matchGroup.sections.push(section);
  });
  // Require the complete multichannel launch shape. Other reports retain their
  // existing renderer, and incomplete drafts cannot imply missing deliverables.
  if (!groups.every((group) => group.sections.some((section) => section.body.length > 60))) return null;
  return { intro, groups: groups.map(({ name, sections }) => ({ name, sections })) };
}
