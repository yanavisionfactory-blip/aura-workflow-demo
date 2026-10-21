import { pageHTML } from './websiteContentExport.mjs';

const providers = [
  { id: 'wordpress-preview', name: 'WordPress', scope: 'Selected client CMS',
    artifact: 'unpublished_page_preview', summary: 'Five unpublished page payloads prepared',
    detail: 'Draft bodies, original routes, SEO fields and asset requirements for the selected WordPress client.' },
  { id: 'shopify-preview', name: 'Shopify', scope: 'Alternative CMS demonstration',
    artifact: 'unpublished_page_preview', summary: 'Five unpublished store page payloads prepared',
    detail: 'The saved review content mapped to Shopify page previews. No Shopify authorization or API write is implied.' },
  { id: 'woocommerce-preview', name: 'WooCommerce', scope: 'WordPress commerce handoff',
    artifact: 'wordpress_page_handoff', summary: 'Five WordPress content routes mapped',
    detail: 'WooCommerce runs within WordPress. These are WordPress content-page handoffs; no products, orders or checkout settings are changed.' },
  { id: 'bigcommerce-preview', name: 'BigCommerce', scope: 'Alternative CMS demonstration',
    artifact: 'unpublished_page_preview', summary: 'Five unpublished store page payloads prepared',
    detail: 'The same content mapped to BigCommerce page previews. A store destination and verified connection are still required for live staging.' },
];

// A deterministic local preview, never a provider response or execution receipt.
// Opening saved results cannot call a CMS, approve content or mutate the packet.
export function websiteCMSPreview(packet) {
  if (!Array.isArray(packet?.pages) || packet.pages.length !== 5) {
    throw new Error('The CMS preview requires the saved five-page content package');
  }
  return {
    kind: 'website_cms_simulation', schema_version: 1, mode: 'simulated',
    client: packet.client, source_content_receipt: packet.execution?.id || null,
    external_calls: 0, cms_records_created: 0, live_pages_modified: false,
    approvals_recorded: false,
    notice: 'Simulated CMS outputs generated locally from the saved content package. No provider connection, approval or CMS write is represented as completed.',
    tools: providers.map((provider) => ({
      ...provider, mode: 'simulated', status: 'preview_ready',
      external_calls: 0, remote_records_created: 0, connection_verified: false,
      pages: packet.pages.map((page) => {
        const source = new URL(page.url);
        if (source.protocol !== 'https:' || source.username || source.password) throw new Error('A safe source URL is required');
        const handle = source.pathname.split('/').filter(Boolean).join('-') || 'home';
        return {
          mode: 'simulated', preview_id: `simulated-${provider.id}-${page.page_id}`,
          page_id: page.page_id, content_version: page.version,
          source_live_url: page.url, proposed_path: provider.name === 'Shopify' ? `/pages/${handle}` : source.pathname,
          remote_id: null, remote_url: null, publish_state: 'unpublished',
          approval_status: 'pending', title: page.h1, purpose: page.purpose,
          body_html: pageHTML(page),
          content_blocks: structuredClone(page.sections), faqs: structuredClone(page.faqs || []),
          seo: { page_title: page.page_title, meta_description: page.meta_description },
          cta: { label: page.cta_label, target: page.cta_target },
          asset_requirements: structuredClone(page.assets),
          ...(provider.name === 'WooCommerce' ? { cms_owner: 'WordPress', products_created: 0, orders_changed: 0 } : {}),
        };
      }),
    })),
  };
}
