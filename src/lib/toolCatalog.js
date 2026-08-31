// Single source of truth for the tools AURA can connect to. Shared by the
// Connections panel (proactive) and the in-plan "Uses" line picker (reactive)
// so both surfaces show the same tools, icons, and connection methods.

export const CATALOG = [
  { name: "Gmail", icon: "📧", desc: "Read and send email" },
  { name: "Airtable", icon: "🗃️", desc: "Read and write records" },
  { name: "Google Drive", icon: "🗂️", desc: "Access files and folders" },
  { name: "Slack", icon: "💬", desc: "Send messages to channels" },
  { name: "Salesforce", icon: "☁️", desc: "Read and update CRM records" },
  { name: "Google Calendar", icon: "📅", desc: "Read and create events" },
  { name: "HubSpot", icon: "🔶", desc: "Manage contacts and deals" },
  { name: "Mailchimp", icon: "🐵", desc: "Manage audiences, contacts, and campaigns" },
  { name: "Canva", icon: "🎨", desc: "Create, organize, and export designs" },
  { name: "Notion", icon: "📝", desc: "Read and edit notes and docs" },
  { name: "Google Sheets", icon: "📊", desc: "Read and write spreadsheets" },
  { name: "Shopify", icon: "🛍️", desc: "Manage orders and products" },
  { name: "Instagram", icon: "📸", desc: "Publish and analyze posts" },
  { name: "TikTok", icon: "🎵", desc: "Read videos and publish approved content" },
  { name: "QuickBooks", icon: "🧾", desc: "Read invoices and financials" },
  { name: "Stripe", icon: "💳", desc: "Charge customers and subscriptions" },
  { name: "Meta Ads", icon: "📈", desc: "Pull ad campaign performance" },
  { name: "Jira", icon: "✅", desc: "Create and track Atlassian issues" },
  { name: "Confluence", icon: "📚", desc: "Read and update Atlassian knowledge bases" },
  { name: "ClickUp", icon: "✔️", desc: "Manage tasks, lists, and workspaces" },
  // Internal tool with no standard connection — connects via the AURA Interface
  // learn flow. Same persistent store once connected.
  { name: "Creator Approvals", icon: "🔌", desc: "Submit creators for approval", interface: true },
  // Specialized creator-data APIs — return VERIFIED TikTok stats + contact
  // emails. AURA proposes these for creator-discovery goals; without one,
  // discovery falls back to LLM web search and results are marked unverified.
  { name: "Modash", icon: "🔍", desc: "Verified creator stats & contact emails", apiKey: true, specialty: "creator-data" },
  { name: "HypeAuditor", icon: "📊", desc: "Influencer analytics & contact emails", apiKey: true, specialty: "creator-data" },
  { name: "Apify", icon: "🕷️", desc: "Scrape & verify TikTok profiles", apiKey: true, specialty: "scraping" },
];
