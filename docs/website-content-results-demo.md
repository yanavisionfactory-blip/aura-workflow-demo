# Website content results and public demonstration

The main five-page content package leads Results. Its four tabs are Pages,
Changes, Approvals and Developer handoff. The pages show the complete revised
copy, search listing, button destination and image instructions. Approval rows
use readable page names and concrete next steps. Developer files remain
available as a ZIP, with exact content versions and source evidence preserved
inside that handoff.

## One set of simulated tool outcomes

A single Results by tool section follows the main result. It is always visible,
with no simulation toggle, earlier source-tool result list, duplicate tool chips
or separate raw-output tab. Each of the four cards explains:

- The tool's part of the task.
- What its simulated outcome contains.
- What the user should review next.
- A named View in WordPress, Shopify, WooCommerce or BigCommerce action.

AURA prepared the content package. The four CMS previews are alternative
handoffs for those same five pages, rather than four claims of independent copy
generation. Every card and tool screen is visibly simulated. Opening them does
not connect a CMS, create a record, approve content or modify a live page.

The tool screens use readable page names, review statuses, search listings,
button text and image instructions. They also explain their contribution to the
task. Internal page IDs, version hashes, execution receipts, raw JSON and HTML
are not displayed in these user flows. Programmatic evidence stays in the
saved packet and developer download; it is not discarded or rewritten.

## Separate public walkthrough

The static build at `showcase/website-content/` reuses AURA's task, plan, review,
prepared execution, main result and simulated CMS screen components without
sign-in or access to private runs.

- `?tour=1`: guided walkthrough with captions, Pause, Back and Next.
- `?screen=results`: the main result followed by the single tool-outcome section.
- `?screen=video`: captioned MP4 and download.
- `?scene=0` through `?scene=13`: paused scenes for capture and QA.

The historical example uses public Kastner Hill Learning website material and
the saved revised page copy. Source headings and asset instructions are
selected or summarized; images are not reproduced. Approved brief, image
permissions, named reviewer, asset storage and project tools remain separate
confirmations. The demonstration implies no agency/client endorsement.

The public build excludes account clients and prohibits API connections through
CSP. It contains no private run or credential identifiers. Feedback stays local.
The Pages build renders the 14 scenes in a fresh build-time browser that permits
only its local static server, then uses ffmpeg to publish a 113-second MP4,
VTT captions and poster. This prepared video is not evidence of live integrations.

Validation: `npm test`, `npm run lint`, `npm run build`, plus the generated-video
build and browser checks for one outcome section, named tool navigation and
absence of raw technical output in rendered views.
