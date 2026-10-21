// Display copy describes the simulated task contribution, never a live receipt.
const outcomes = {
  WordPress: {
    part: 'Prepare the five website pages for review',
    result: 'Five unpublished website drafts, arranged as pages in WordPress.',
    includes: ['Revised page text and headings', 'Search titles, descriptions and page addresses', 'Buttons and image instructions for each page'],
    next: 'Review the copy and image permissions before creating real WordPress drafts.',
    destination: 'Website content management',
  },
  Shopify: {
    part: 'Prepare the content pages for an online store',
    result: 'The same five pages arranged in a Shopify store’s Pages area.',
    includes: ['Store page titles and full page text', 'Search listings and suggested page addresses', 'Calls to action and image requirements'],
    next: 'Check that Shopify is the chosen destination, then approve the pages and images.',
    destination: 'Alternative store preview',
  },
  WooCommerce: {
    part: 'Prepare website content for a WordPress store',
    result: 'Five content pages ready to review alongside a WooCommerce store.',
    includes: ['Page copy managed through WordPress', 'Search listings and calls to action', 'Image instructions, with permissions still to review'],
    next: 'Approve the content pages in WordPress. Products, orders and checkout are outside this task.',
    destination: 'WordPress store content',
  },
  BigCommerce: {
    part: 'Prepare the storefront’s information pages',
    result: 'The same five drafts arranged as BigCommerce Web Pages.',
    includes: ['Five complete storefront content pages', 'Search titles, descriptions and page addresses', 'Buttons and image instructions for the developer'],
    next: 'Confirm the store destination and approve the content before creating real drafts.',
    destination: 'Alternative store preview',
  },
};
export function websiteToolOutcome(name) { return outcomes[name]; }
export function websitePageName(url) {
  const path = new URL(url).pathname;
  return path === '/' ? 'Home' : path.split('/').filter(Boolean).join(' / ').split('-').map(word => ['sat', 'ap'].includes(word) ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}
