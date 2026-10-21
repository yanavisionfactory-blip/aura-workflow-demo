# Website content results and CMS preview

Open a completed five-page website content run in AURA. The Results page has
"What happened" rows and an action for each recorded output.
Full pages, comparisons, pending approvals, developer handoff and source receipts
remain inspectable.

The standard Results view also shows a **Shopify · Simulated** preview card with
a **View in Shopify** action. It opens the five saved drafts in the simulated
Shopify admin without requiring the all-CMS toggle or a special query string.

Choose **Preview simulated CMS outputs** to show the requested end-to-end CMS
handoff demonstration. The URL retains `cmsPreview=simulated` so the same view
can be reopened and shared with someone who has access to the saved run.

The preview creates four local output envelopes from the exact saved content:

- WordPress: five unpublished page previews for the selected client CMS.
- Shopify: five unpublished page previews for an alternative CMS demonstration.
- WooCommerce: five WordPress page handoffs, without product or order mutations.
- BigCommerce: five unpublished page previews for an alternative CMS demonstration.

**View in WordPress**, **View in Shopify**, **View in WooCommerce** and **View in
BigCommerce** open separate simulated admin screens at
`/runs/:runId/tools/:toolSlug`. Each screen uses its tool's navigation and colors,
shows all five draft pages, and provides a page editor, SEO and asset tabs, search
and an unpublished page preview. The simulation label stays visible. Back to AURA
results returns to the same package and simulation view.

The screens load the same authenticated, tenant-scoped saved run as Results.
They do not contact a CMS or collect credentials. Invalid tool routes and
inaccessible runs cannot create a tool screen or bypass workspace access.

Every envelope and page identifies itself as simulated, preserves the source
page URL and exact content version, retains pending approval, and has null remote
IDs and URLs. The preview makes no network calls and adds no execution receipts
or connection claims to the saved workflow. Actual source reads and model output
stay separate. Download the simulation JSON using **Download simulated tool
outputs**; the standard CMS-ready archive continues to report zero CMS records.

Live staging still requires the selected client's verified CMS connection and
approval of the exact content and assets. Opening the demonstration never
satisfies either requirement.

Validation: `npm test`, `npm run lint`, `npm run build`.

## Main-result order and separate public walkthrough

The Results view opens with the five-page content package, page comparison,
approval tracker and developer handoff. Results by tool follow that primary
panel. **Explore results by tool** jumps down to those entries.

The separate static build at `showcase/website-content/` reuses the AURA command,
plan, review, execution, results and simulated-admin components. It is accessible
without sign-in and never loads private saved runs. Entry points:

- `?tour=1`: guided walkthrough with captions, Pause, Back and Next.
- `?screen=results`: main result first, then per-tool previews.
- `?screen=video`: captioned MP4 walkthrough and download.
- `?scene=0` through `?scene=13`: paused walkthrough scenes for capture and QA.

The historical public-site example uses Kastner Hill Learning. Revised body copy
and source content-version references come from the saved preparation package.
Source headings and asset instructions are selected or summarized; images are
not reproduced. No agency/client endorsement, approved brief, approved assets or
confirmed client storage/approval/project tools are implied. All approvals stay
pending and all CMS records remain simulated.

A restrictive Content Security Policy prohibits fetch/XHR/WebSocket calls.
Account, OAuth and upload clients are excluded from the build graph. The static
snapshot contains no private run, workspace or credential identifiers. Feedback
is copy-only and local to the browser. The video uses interface views rendered from the isolated static build
and captions; it is prepared playback rather than proof of live integrations.

The Pages release renders all 14 paused scenes in a fresh headless browser that
allows only the local static server, then uses ffmpeg to create the MP4 and VTT.
This build-time renderer is separate from user sessions and the live control
plane. A review artifact preserves the MP4, captions and poster for download.
