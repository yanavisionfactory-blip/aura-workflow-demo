// Navigation over an accepted report body, never an imported execution receipt.
export function campaignReportGroups(body) {
  if (typeof body !== "string") return null;
  const groups = [
    ["Brief", /brief|objective|budget|channel plan|scope|source|execution|consistency/i],
    ["Google Ads", /search|responsive|\brsa\b|keyword|negative/i],
    ["Social ads", /social|facebook|instagram|meta|linkedin/i],
    ["Business Profile", /business profile|\bgbp\b/i],
    ["Indoor screens", /screen|signage/i],
    ["Reel", /\breels?\b|storyboard|15.second/i],
    ["Booking and source checks", /vagaro|booking destination|service verification|account (?:access|checks)|source checks/i],
    ["Assets", /asset|creative checklist|rights/i],
    ["Approvals and handoff", /approv|handoff|implementation|measurement|landing|manual/i],
  ].map(([name, pattern]) => ({ name, pattern, sections: [] }));
  const topHeadings = [...body.matchAll(/^# ([^\n]+)\n/gm)];
  // Reports may use H1 for each campaign section and H2 for its details.
  // A single document-title H1 must not swallow normal H2 channel sections.
  const topTitles = topHeadings.map((match) => match[1]);
  const sectionLevelOne = topTitles.some((title) => /brief/i.test(title))
    && topTitles.some((title) => /asset/i.test(title))
    && topTitles.some((title) => /approv/i.test(title));
  const headings = sectionLevelOne ? topHeadings : [...body.matchAll(/^## ([^\n]+)\n/gm)];
  if (!headings.length) return null;
  const intro = body.slice(0, headings[0].index).trim();
  headings.forEach((match, index) => {
    const section = { title: match[1].trim(), body: body.slice(match.index,
      headings[index + 1]?.index ?? body.length).trim() };
    // Asset requirements for a channel belong to Assets, not to ad copy.
    const matchGroup = groups.slice(7).find((group) => group.pattern.test(section.title))
      || groups.slice(5, 7).find((group) => group.pattern.test(section.title))
      || groups.slice(1, 5).find((group) => group.pattern.test(section.title)) || groups[0];
    matchGroup.sections.push(section);
  });
  // A campaign can legitimately exclude Search or screens. Navigation reflects
  // saved content, not a claim that every possible channel was requested or run.
  // Keep ordinary reports in their existing renderer and require the core
  // campaign brief, asset review, approval/handoff and at least one channel.
  const populated = (group) => group.sections.some((section) => section.body.length > 60);
  if (![groups[0], groups[7], groups[8]].every(populated)
      || !groups.slice(1, 6).some(populated)) return null;
  return { intro, groups: groups.filter((group) => group.sections.length)
    .map(({ name, sections }) => ({ name, sections })) };
}
