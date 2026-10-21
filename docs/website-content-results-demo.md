# Website content results and CMS preview

Open a completed five-page website content run in AURA. The Results page has
"What happened" rows and a "View in AURA" action for each recorded output.
Full pages, comparisons, pending approvals, developer handoff and source receipts
remain inspectable.

Choose **Preview simulated CMS outputs** to show the requested end-to-end CMS
handoff demonstration. The URL retains `cmsPreview=simulated` so the same view
can be reopened and shared with someone who has access to the saved run.

The preview creates four local output envelopes from the exact saved content:

- WordPress: five unpublished page previews for the selected client CMS.
- Shopify: five unpublished page previews for an alternative CMS demonstration.
- WooCommerce: five WordPress page handoffs, without product or order mutations.
- BigCommerce: five unpublished page previews for an alternative CMS demonstration.

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
