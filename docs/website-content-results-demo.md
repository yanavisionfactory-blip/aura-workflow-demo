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
