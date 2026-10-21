export const originalPrompt = `Prepare a five-page website content package for one Lion’s Share Digital client.

Confirm the selected client’s CMS. Confirm asset storage, approval and project-management tools separately.

Use the existing website, sitemap, brand brief and approved assets. For each page, prepare its purpose, URL, headings, revised copy, CTA, page title, meta description and asset requirements.

Deliver a page-by-page change comparison, approval tracker and developer handoff. After approval, prepare unpublished CMS drafts through a verified connection if supported; otherwise provide structured files. Preserve live pages.`;
const step = (tool, title, action, output) => ({tool,title,action,output,iWill:action[0].toLowerCase()+action.slice(1),riskLevel:'read',flow:[{label:'Uses',value:tool}]});
export const workflowSteps = [
  step('Existing website & sitemap','Confirm the five pages','Review the saved public-site and sitemap evidence','Five existing page routes retained. This demo uses a saved snapshot, not live requests.'),
  step('WordPress','Confirm the CMS separately','Review historical public WordPress discovery','Public CMS evidence is distinct from authenticated draft access.'),
  step('Source files & approvals','Check the working brief and assets','Show missing client-tool and asset confirmations','Approved brief, asset rights, approver and project tool remain unconfirmed.'),
  step('AURA content package','Prepare the main result','Open the five complete review drafts','Purpose, headings, full copy, CTA, SEO and asset requirements are ready to inspect.'),
  step('AURA review','Compare and hand off','Inspect changes, pending approvals and developer instructions','Five exact source content-version references; structured handoff; zero live changes.'),
  step('WordPress · simulated','Preview the WordPress handoff','Explore five unpublished page previews','Local admin simulation only; no remote record or connection.'),
  step('Shopify · simulated','Preview alternative CMS outputs','Explore Shopify, WooCommerce and BigCommerce screens','Separate, clearly labelled tool screens; no provider calls or commerce changes.'),
];
export const tour = [
  {phase:'input',title:'Describe the outcome',caption:'Start with a five-page content request. The workflow must confirm the CMS and the client’s other tools separately.',seconds:7},
  {phase:'plan',title:'Review the plan',caption:'AURA separates website evidence, CMS discovery, source assets, content preparation and simulated CMS handoffs.',seconds:8},
  {phase:'review',title:'Check the inputs',caption:'The public example uses Kastner Hill Learning pages. The approved brief, assets, client tools and named reviewer remain unconfirmed.',seconds:9},
  {phase:'execution',title:'Follow prepared playback',caption:'This is a local replay of the workflow, with no live provider calls, account connections or website changes.',seconds:10},
  {phase:'results',title:'Read the main result first',caption:'The five-page package comes first. Select a page to inspect its purpose, complete copy, CTA, SEO and asset requirements.',seconds:10},
  {phase:'results',focus:{tab:'Changes',page:'p02'},title:'Compare the proposed changes',caption:'Review current source excerpts beside revised headings, titles and meta descriptions. Source excerpts are historical, not a live crawl.',seconds:8},
  {phase:'results',focus:{tab:'Approvals'},title:'Keep approval explicit',caption:'All five drafts await copy and asset approval. No reviewer decision is implied by running or viewing this demo.',seconds:8},
  {phase:'results',focus:{tab:'Developer handoff'},title:'Hand off structured files',caption:'Download HTML and metadata. Actual staging requires approval and a verified client connection; live records stay unchanged.',seconds:8},
  {phase:'results',focus:{section:'tools'},title:'Then inspect results by tool',caption:'Tool outputs follow the main package. Open a named CMS screen to explore the proposed handoff.',seconds:8},
  {phase:'tool',tool:'wordpress',title:'View in WordPress',caption:'The simulated WordPress admin contains five unpublished page previews from the same content package.',seconds:7},
  {phase:'tool',tool:'shopify',page:'p02',title:'View in Shopify',caption:'Open the simulated Shopify page editor. Content, SEO and assets remain linked to the same draft version.',seconds:8},
  {phase:'tool',tool:'woocommerce',title:'View in WooCommerce',caption:'WooCommerce content is handed off as WordPress pages. This preview changes no products, orders, payments or checkout.',seconds:7},
  {phase:'tool',tool:'bigcommerce',title:'View in BigCommerce',caption:'The BigCommerce simulation shows the alternative unpublished Web Pages handoff, with no connected account.',seconds:7},
  {phase:'feedback',title:'Ask for a practitioner’s assessment',caption:'Review the practical value, limitations and requirements for a live pilot. Feedback stays local until you choose to share it.',seconds:8},
];
export const validPhases = new Set(['input','plan','review','execution','results','tool','feedback','video']);
export function executionSteps(completed) { return workflowSteps.map((item,index)=>({...item,status:index<completed?'completed':index===completed?'running':'pending',liveOutput:index<completed?item.output:''})); }
export function toolHref(id) { const slug=String(id).replace(/-preview$/,''); return ['wordpress','shopify','woocommerce','bigcommerce'].includes(slug) ? `?screen=tool&tool=${slug}` : null; }
