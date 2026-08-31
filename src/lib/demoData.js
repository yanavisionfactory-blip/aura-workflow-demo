import { CAMPAIGN_MOCK, FOLLOWUPS_MOCK, JIRA_MOCK, CRM_MOCK } from "@/lib/mockWorkflows";

// Simulated connection states for tools. `true` = connected, `false` = shows "Connect <tool>".
export const CONNECTIONS = {
  "Meta Ads": true,
  HubSpot: false,
  Mailchimp: false,
  Salesforce: false,
  Gmail: true,
  Slack: false,
  "Google Sheets": true,
  "Google Calendar": true,
  Notion: false,
  TikTok: false,
  Jira: false,
  Confluence: false,
  ClickUp: false,
  Stripe: false,
  "AURA Intelligence": true,
  // Internal tool with no standard OAuth integration — connects through the
  // AURA Interface "learn the tool" flow instead of a normal connection.
  "Creator Approvals": false,
};

// Tools that have no standard connection and must be connected via the AURA
// Interface learn flow (paste URL → AURA analyzes → discover capabilities →
// allow & connect). Same persistent store as normal connections once connected.
export const INTERFACE_TOOLS = {
  "Creator Approvals": true,
};

export function connectionFor(tool) {
  if (tool in CONNECTIONS) return CONNECTIONS[tool];
  return true; // unknown tools default to connected for the demo
}

// Starter prompts shown on the first screen. They are intentionally cross-functional
// (marketing, customer success, engineering, sales/ops) so the product reads as a
// general-purpose automation platform rather than a marketing/reporting tool.
// Picking one submits it as a normal user request — AURA plans and executes it live.
export const WORKFLOW_EXAMPLES = [
  {
    id: "weekly-campaign-report",
    title: "Weekly campaign report",
    subtitle: "Summarize last week's campaign results",
    prompt:
      "Build this week's campaign report from Meta Ads and email a campaign-by-campaign breakdown to the marketing team",
    mock: CAMPAIGN_MOCK,
  },
  {
    id: "customer-follow-ups",
    title: "Prepare customer follow-ups",
    subtitle: "Draft check-ins for customers you haven't reached",
    prompt:
      "Find customers I haven't followed up with this week and draft a personalized check-in email for each one",
    mock: FOLLOWUPS_MOCK,
  },
  {
    id: "research-to-jira",
    title: "Turn research into Jira tasks",
    subtitle: "Create a Jira task for every action item",
    prompt:
      "Turn the action items from my research notes into Jira tasks, one task per item, assigned to the right person",
    mock: JIRA_MOCK,
  },
  {
    id: "update-crm-from-notes",
    title: "Update CRM from meeting notes",
    subtitle: "Sync owners and action items into your CRM",
    prompt:
      "Update HubSpot with the action items and owners captured in my meeting notes",
    mock: CRM_MOCK,
  },
];