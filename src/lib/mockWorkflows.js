// Scripted demo workflows that pause at one step so the failure / recovery
// screen is reachable from the first screen. Each of the four example cards
// gets its own themed failure, and each `results` block is shaped as
// "proof of work" — one line per outcome with a count, a deep link, and a
// needs-attention line where something was skipped or flagged.
//
// Each plan step also carries a `preview` block describing the concrete output
// AURA produced for that step (a dataset, an email draft, a list of records…)
// so the review screen can show the actual thing the user is approving.

const campaignMock = {
  plan: {
    interpretation:
      "You want to pull this week's campaign performance from Meta Ads, build a campaign-by-campaign breakdown, and email it to the marketing team.",
    estimatedTime: "~9 seconds",
    steps: [
      {
        tool: "Meta Ads",
        title: "Get this week's campaign performance",
        iWill: "pull this week's campaign performance from Meta Ads",
        action: "Get this week's campaign performance from Meta Ads",
        detail: "",
        reason: "We need the campaign metrics before building the report.",
        output: "performance for 5 campaigns",
        flow: [
          { label: "Uses", value: "Meta Ads" },
          { label: "Creates", value: "performance for 5 campaigns" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "table",
          title: "5 campaigns pulled from Meta Ads",
          summary: "Pulled 5 campaigns from Meta Ads",
          previewLabel: "View campaign data",
          columns: ["Campaign", "Spend", "CTR", "CPL", "Leads"],
          rows: [
            ["Q3 Launch", "$4,200", "2.1%", "$110", "38"],
            ["Brand awareness", "$1,800", "1.4%", "—", "—"],
            ["Retargeting", "$950", "3.2%", "$45", "21"],
            ["Always-on search", "$2,300", "4.8%", "$62", "37"],
            ["Holiday teaser", "$600", "2.0%", "$120", "5"],
          ],
        },
      },
      {
        tool: "Google Sheets",
        title: "Build the breakdown",
        iWill: "build a campaign-by-campaign breakdown in Google Sheets",
        action: "Build a campaign-by-campaign breakdown in Google Sheets",
        detail: "",
        reason: "",
        output: "a breakdown sheet",
        flow: [
          { label: "Uses", value: "Google Sheets" },
          { label: "Creates", value: "a breakdown sheet" },
        ],
        riskLevel: "modify",
        riskNote: "You'll review the breakdown before it's saved.",
        preview: {
          type: "table",
          title: "Breakdown to save in Google Sheets",
          summary: "Save breakdown to Google Sheets",
          previewNote: "5 campaigns · $9,850 spend · 101 leads",
          previewLabel: "Preview what will be saved",
          columns: ["Campaign", "Spend", "CTR", "CPL", "Leads"],
          rows: [
            ["Q3 Launch", "$4,200", "2.1%", "$110", "38"],
            ["Brand awareness", "$1,800", "1.4%", "—", "—"],
            ["Retargeting", "$950", "3.2%", "$45", "21"],
            ["Always-on search", "$2,300", "4.8%", "$62", "37"],
            ["Holiday teaser", "$600", "2.0%", "$120", "5"],
          ],
        },
      },
      {
        tool: "Gmail",
        title: "Email the report",
        iWill: "email the breakdown to the marketing team",
        action: "Email the breakdown to the marketing team",
        detail: "",
        reason: "",
        output: "a report email",
        flow: [
          { label: "Uses", value: "Gmail" },
          { label: "Creates", value: "a report email" },
        ],
        riskLevel: "modify",
        riskNote: "You'll review the email before it's sent.",
        preview: {
          type: "email",
          to: "marketing-team@acme.com",
          summary: "Send report to marketing team",
          previewNote: "marketing-team@acme.com",
          previewLabel: "Preview email",
          subject: "This week's campaign performance",
          body:
            "Hi team,\n\nHere's this week's campaign-by-campaign breakdown pulled from Meta Ads. Total spend was $9,850 across 5 campaigns, with 101 leads at an average CPL of $84.\n\nThe full breakdown is attached as a Google Sheet. A couple of things to flag:\n- Retargeting is performing well (CPL $45)\n- Holiday teaser is still warming up\n\nLet me know if you'd like a deeper cut.\n\n— AURA",
        },
      },
    ],
  },
  execSteps: [
    {
      tool: "Meta Ads",
      action: "Get this week's campaign performance from Meta Ads",
      duration: "1.3s",
      riskLevel: "read",
      liveOutput: "→ 5 active campaigns found",
    },
    {
      tool: "Google Sheets",
      action: "Build a campaign-by-campaign breakdown in Google Sheets",
      duration: "1.0s",
      riskLevel: "modify",
      liveOutput: "→ Breakdown created with 5 campaigns",
    },
    {
      tool: "Gmail",
      action: "Email the breakdown to the marketing team",
      duration: "1.4s",
      riskLevel: "modify",
      liveOutput: "→ ⚠ marketing-team@ alias no longer exists",
    },
  ],
  errorStep: {
    index: 2,
    what: "Couldn't send to marketing-team@acme.com.",
    why: "The address was renamed to growth@acme.com last week.",
    fix:
      "Send the report to growth@ instead with the breakdown still attached. You can update the saved alias later.",
    fixShort: "Change the recipient to growth@acme.com and retry.",
    fixFrom: "marketing-team@acme.com",
    fixTo: "growth@acme.com",
    buttonLabel: "Use growth@ & retry",
  },
  results: {
    title: "Campaign report sent",
    summary:
      "Built a campaign-by-campaign breakdown of 5 campaigns from Meta Ads and emailed it to the growth team.",
    metrics: [
      { value: "5", label: "campaigns reported" },
      { value: "1", label: "report emailed" },
      { value: "~12 min", label: "time saved" },
    ],
    outcomes: [
      {
        type: "metric",
        count: 5,
        title: "campaigns pulled from Meta Ads",
        detail: "This week's active campaigns.",
        link: "https://business.facebook.com/adsmanager/manage/campaigns",
        linkLabel: "Open in Meta Ads",
      },
      {
        type: "document",
        count: 1,
        title: "breakdown built in Google Sheets",
        detail: "Spend, CTR, CPL and leads per campaign.",
        link: "https://docs.google.com/spreadsheets/d/1a2b3c4d5e6f/edit",
        linkLabel: "Open in Sheets",
        items: [
          { label: "Q3 Launch", detail: "Spend $4,200 · CTR 2.1% · 38 leads" },
          { label: "Brand awareness", detail: "Spend $1,800 · 92k impressions" },
          { label: "Retargeting", detail: "Spend $950 · CPL $12 · 21 leads" },
        ],
      },
      {
        type: "email",
        count: 1,
        title: "report emailed to growth@",
        detail: "Breakdown attached.",
        link: "https://mail.google.com/mail/u/0/#sent",
        linkLabel: "Open in Gmail",
      },
      {
        type: "alert",
        count: 1,
        title: "alias needs updating",
        detail: "marketing-team@ no longer exists — update to growth@.",
        attention: true,
        link: "https://mail.google.com/mail/u/0/#settings/aliases",
        linkLabel: "View issue",
      },
    ],
    breakdown: {
      title: "Campaign-by-campaign breakdown",
      columns: ["Campaign", "Spend", "CTR", "CPL", "Leads"],
      rows: [
        ["Q3 Launch", "$4,200", "2.1%", "$110", "38"],
        ["Brand awareness", "$1,800", "1.4%", "—", "—"],
        ["Retargeting", "$950", "3.2%", "$45", "21"],
        ["Always-on search", "$2,300", "4.8%", "$62", "37"],
        ["Holiday teaser", "$600", "2.0%", "$120", "5"],
      ],
      footnote: "This week's performance, pulled from Meta Ads.",
    },
    nextSteps: [
      "Update the saved marketing alias to growth@",
      "Schedule this report to run every Monday",
      "Add last week's comparison to the breakdown",
    ],
  },
};

const followupsMock = {
  plan: {
    interpretation:
      "You want to find customers you haven't contacted this week and draft a personalized check-in email for each one.",
    estimatedTime: "~8 seconds",
    steps: [
      {
        tool: "HubSpot",
        title: "Find customers needing follow-up",
        iWill: "find customers you haven't followed up with this week",
        action: "Find customers you haven't followed up with this week",
        detail: "",
        reason: "We need the list before drafting.",
        output: "4 customers needing follow-up",
        flow: [
          { label: "Uses", value: "HubSpot" },
          { label: "Creates", value: "4 customers needing follow-up" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "list",
          title: "4 customers needing follow-up",
          summary: "Found 4 customers needing follow-up",
          previewLabel: "View customers",
          items: [
            { label: "Acme Corp", detail: "Last contact 12 days ago" },
            { label: "Bloom Health", detail: "Last contact 9 days ago" },
            { label: "Globex", detail: "Last contact 15 days ago" },
            { label: "Northwind", detail: "Last contact 21 days ago" },
          ],
        },
      },
      {
        tool: "HubSpot",
        title: "Pull last interaction",
        iWill: "pull the last interaction for each customer",
        action: "Pull the last interaction for each customer",
        detail: "",
        reason: "",
        output: "context for 4 customers",
        flow: [
          { label: "Uses", value: "HubSpot" },
          { label: "Creates", value: "context for 4 customers" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "list",
          title: "Last interaction per customer",
          summary: "Pulled last interaction for 4 customers",
          previewLabel: "View context",
          items: [
            { label: "Acme Corp", detail: "Replied to pricing email on Aug 4" },
            { label: "Bloom Health", detail: "Demo call on Aug 5" },
            { label: "Globex", detail: "Sent onboarding docs on Aug 1" },
            { label: "Northwind", detail: "No email on file" },
          ],
        },
      },
      {
        tool: "Gmail",
        title: "Draft check-in emails",
        iWill: "draft a personalized check-in email for each customer",
        action: "Draft a personalized check-in email for each customer",
        detail: "",
        reason: "",
        output: "4 check-in drafts",
        flow: [
          { label: "Uses", value: "Gmail" },
          { label: "Creates", value: "4 check-in drafts" },
        ],
        riskLevel: "modify",
        riskNote: "You'll review the drafts before they're saved.",
        preview: {
          type: "email",
          to: "sarah@acmecorp.com",
          summary: "Draft check-in emails for 4 customers",
          previewNote: "4 drafts · first to sarah@acmecorp.com",
          previewLabel: "Preview email",
          subject: "Checking in — anything I can help with?",
          body:
            "Hi Sarah,\n\nIt's been a couple of weeks since we last spoke about your renewal. I wanted to check in and see how things are going, and whether there's anything I can help with on your end.\n\nHappy to jump on a quick call if that's easier.\n\n— AURA on behalf of the team",
          note: "1 of 4 drafts — Bloom Health, Globex, and Northwind follow the same template.",
        },
      },
    ],
  },
  execSteps: [
    {
      tool: "HubSpot",
      action: "Find customers you haven't followed up with this week",
      duration: "1.1s",
      riskLevel: "read",
      liveOutput: "→ 4 customers need follow-up",
    },
    {
      tool: "HubSpot",
      action: "Pull the last interaction for each customer",
      duration: "0.9s",
      riskLevel: "read",
      liveOutput: "→ Context pulled for 4 customers",
    },
    {
      tool: "Gmail",
      action: "Draft a personalized check-in email for each customer",
      duration: "1.4s",
      riskLevel: "modify",
      liveOutput: "→ ⚠ Northwind: no email address on file",
    },
  ],
  errorStep: {
    index: 2,
    what: "Couldn't draft a check-in for Northwind — no email address on file.",
    why: "The Northwind contact record has no email filled in.",
    fix:
      "Skip Northwind for now and draft check-ins for the other 3 customers. You can add Northwind's email and re-run that draft later.",
    fixShort: "Skip Northwind and draft the other 3 check-ins.",
    buttonLabel: "Skip Northwind & retry",
  },
  results: {
    title: "Check-in emails drafted",
    summary:
      "Drafted personalized check-in emails for 3 of 4 customers. Northwind was skipped because there's no email on file.",
    metrics: [
      { value: "4", label: "customers flagged" },
      { value: "3", label: "drafts created" },
      { value: "1", label: "skipped (no email)" },
    ],
    outcomes: [
      {
        type: "crm",
        count: 4,
        title: "customers flagged for follow-up",
        detail: "No contact in the last 7 days.",
        link: "https://app.hubspot.com/contacts",
        linkLabel: "View in HubSpot",
      },
      {
        type: "email",
        count: 3,
        title: "check-in emails drafted",
        detail: "Saved as drafts in Gmail — review and send.",
        link: "https://mail.google.com/mail/u/0/#drafts",
        linkLabel: "Open in Gmail",
        items: [
          { label: "Acme Corp", detail: "Check-in drafted" },
          { label: "Bloom Health", detail: "Check-in drafted" },
          { label: "Globex", detail: "Check-in drafted" },
        ],
      },
      {
        type: "alert",
        count: 1,
        title: "customer needs attention",
        detail: "Northwind has no email on file.",
        attention: true,
        link: "https://app.hubspot.com/contacts/445211",
        linkLabel: "View issue",
      },
    ],
    nextSteps: [
      "Add Northwind's email to HubSpot and re-run their draft",
      "Review and send the drafts when ready",
      "Schedule a follow-up reminder for next week",
    ],
  },
};

const jiraMock = {
  plan: {
    interpretation:
      "You want to read your research notes, turn each action item into a Jira task, and assign each to the right person.",
    estimatedTime: "~9 seconds",
    steps: [
      {
        tool: "Notion",
        title: "Read the action items",
        iWill: "read the action items from your research notes",
        action: "Read the action items from your research notes",
        detail: "",
        reason: "We need the action items before creating tasks.",
        output: "6 action items",
        flow: [
          { label: "Uses", value: "Notion" },
          { label: "Creates", value: "6 action items" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "list",
          title: "6 action items extracted from notes",
          summary: "Extracted 6 action items from notes",
          previewLabel: "View action items",
          items: [
            { label: "Redesign onboarding flow", detail: "Owner: Dana" },
            { label: "Update API docs", detail: "Owner: Sam" },
            { label: "Fix checkout bug", detail: "Owner: Priya M." },
            { label: "Q4 roadmap sync", detail: "Owner: Dana" },
            { label: "Customer survey", detail: "Owner: Sam" },
            { label: "Migration plan", detail: "Owner: Priya M." },
          ],
        },
      },
      {
        tool: "AURA Intelligence",
        title: "Match assignees",
        iWill: "match each action item to the right assignee",
        action: "Match each action item to the right assignee",
        detail: "",
        reason: "",
        output: "assignees for 6 items",
        flow: [
          { label: "Uses", value: "AURA Intelligence" },
          { label: "Creates", value: "assignees for 6 items" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "list",
          title: "Assignee matched per action item",
          summary: "Matched assignees for 6 items",
          previewLabel: "View matches",
          items: [
            { label: "Redesign onboarding flow", detail: "→ Dana (design lead)" },
            { label: "Update API docs", detail: "→ Sam (platform)" },
            { label: "Fix checkout bug", detail: "→ Priya M. (frontend)" },
            { label: "Q4 roadmap sync", detail: "→ Dana" },
            { label: "Customer survey", detail: "→ Sam" },
            { label: "Migration plan", detail: "→ Priya M." },
          ],
        },
      },
      {
        tool: "Jira",
        title: "Create the Jira tasks",
        iWill: "create a Jira task for each action item",
        action: "Create a Jira task for each action item",
        detail: "",
        reason: "",
        output: "6 Jira tasks",
        flow: [
          { label: "Uses", value: "Jira" },
          { label: "Creates", value: "6 Jira tasks" },
        ],
        riskLevel: "modify",
        riskNote: "You'll review the tasks before they're created.",
        preview: {
          type: "table",
          title: "6 Jira tasks to create in PROJ",
          summary: "Create 6 Jira tasks in PROJ",
          previewNote: "6 tasks across 3 assignees",
          previewLabel: "Preview tasks",
          columns: ["Task", "Assignee", "Project"],
          rows: [
            ["Redesign onboarding flow", "Dana", "PROJ"],
            ["Update API docs", "Sam", "PROJ"],
            ["Fix checkout bug", "Priya M.", "PROJ"],
            ["Q4 roadmap sync", "Dana", "PROJ"],
            ["Customer survey", "Sam", "PROJ"],
            ["Migration plan", "Priya M.", "PROJ"],
          ],
        },
      },
    ],
  },
  execSteps: [
    {
      tool: "Notion",
      action: "Read the action items from your research notes",
      duration: "1.2s",
      riskLevel: "read",
      liveOutput: "→ 6 action items found",
    },
    {
      tool: "AURA Intelligence",
      action: "Match each action item to the right assignee",
      duration: "1.0s",
      riskLevel: "read",
      liveOutput: "→ Assignees matched for 6 items",
    },
    {
      tool: "Jira",
      action: "Create a Jira task for each action item",
      duration: "1.4s",
      riskLevel: "modify",
      liveOutput: "→ ⚠ Priya M. is not a member of PROJ",
    },
  ],
  errorStep: {
    index: 2,
    what: "Couldn't assign the task to Priya M. — not a member of PROJ.",
    why: "Priya is a contractor and hasn't been added to the Jira project.",
    fix:
      "Assign that task to the project lead instead and create the other 5 tasks now. You can add Priya to the project and reassign later.",
    fixShort: "Reassign this task to the project lead and create the other 5.",
    fixFrom: "Priya M.",
    fixTo: "Project lead",
    buttonLabel: "Reassign to lead & retry",
  },
  results: {
    title: "Jira tasks created",
    summary:
      "Created 5 Jira tasks from your research notes and assigned them. One task was reassigned to the project lead (assignee not a project member).",
    metrics: [
      { value: "6", label: "action items" },
      { value: "5", label: "tasks created" },
      { value: "1", label: "reassigned" },
    ],
    outcomes: [
      {
        type: "document",
        count: 6,
        title: "action items extracted from notes",
        detail: "Pulled from your Notion research doc.",
        link: "https://www.notion.so/aura-research-sync-22f1",
        linkLabel: "Open in Notion",
      },
      {
        type: "crm",
        count: 5,
        title: "Jira tasks created",
        detail: "Created in the PROJ project.",
        link: "https://acme.atlassian.net/jira/your-work",
        linkLabel: "Open in Jira",
        items: [
          { label: "PROJ-101 → Dana", detail: "Created" },
          { label: "PROJ-102 → Sam", detail: "Created" },
          { label: "PROJ-103 → Lead", detail: "Reassigned" },
          { label: "PROJ-104 → Dana", detail: "Created" },
          { label: "PROJ-105 → Sam", detail: "Created" },
        ],
      },
      {
        type: "alert",
        count: 1,
        title: "assignee needs attention",
        detail: "Priya M. is not a member of PROJ.",
        attention: true,
        link: "https://acme.atlassian.net/jira/projects/PROJ/people",
        linkLabel: "View issue",
      },
    ],
    nextSteps: [
      "Add Priya M. to the PROJ project and reassign the task",
      "Link the tasks to the current sprint",
      "Save this workflow for the next research sync",
    ],
  },
};

const crmMock = {
  plan: {
    interpretation:
      "You want to read your meeting notes, pull out the action items and owners, and update the matching HubSpot records.",
    estimatedTime: "~8 seconds",
    steps: [
      {
        tool: "Notion",
        title: "Extract action items",
        iWill: "read your meeting notes and extract the action items",
        action: "Read your meeting notes and extract the action items",
        detail: "",
        reason: "We need the action items and owners before updating.",
        output: "4 action items with owners",
        flow: [
          { label: "Uses", value: "Notion" },
          { label: "Creates", value: "4 action items with owners" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "list",
          title: "4 action items extracted from meeting notes",
          summary: "Extracted 4 action items from notes",
          previewLabel: "View action items",
          items: [
            { label: "Acme Corp — follow up on renewal", detail: "Owner: Dana" },
            { label: "Northwind — send pricing", detail: "Owner: Priya" },
            { label: "Globex — schedule demo", detail: "Owner: Sam" },
            { label: "Bloom Health — share case study", detail: "Owner: Dana" },
          ],
        },
      },
      {
        tool: "HubSpot",
        title: "Find matching records",
        iWill: "find the matching records for each action item",
        action: "Find the matching records for each action item",
        detail: "",
        reason: "",
        output: "3 of 4 records found",
        flow: [
          { label: "Uses", value: "HubSpot" },
          { label: "Creates", value: "3 of 4 records found" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "list",
          title: "Matching HubSpot records (3 of 4)",
          summary: "Found 3 of 4 matching records",
          previewLabel: "View matches",
          items: [
            { label: "Acme Corp", detail: "Found" },
            { label: "Northwind", detail: "Found" },
            { label: "Globex", detail: "Found" },
            { label: "Bloom Health", detail: "No company record" },
          ],
        },
      },
      {
        tool: "HubSpot",
        title: "Update the records",
        iWill: "update each record with its action items and owner",
        action: "Update each record with its action items and owner",
        detail: "",
        reason: "",
        output: "3 records updated",
        flow: [
          { label: "Uses", value: "HubSpot" },
          { label: "Creates", value: "3 records updated" },
        ],
        riskLevel: "modify",
        riskNote: "You'll review the updates before they're saved.",
        preview: {
          type: "table",
          title: "3 HubSpot records to update",
          summary: "Update 3 HubSpot records",
          previewNote: "3 records · 4 action items",
          previewLabel: "Preview updates",
          columns: ["Company", "Action item", "Owner"],
          rows: [
            ["Acme Corp", "Follow up on renewal", "Dana"],
            ["Northwind", "Send pricing", "Priya"],
            ["Globex", "Schedule demo", "Sam"],
          ],
        },
      },
    ],
  },
  execSteps: [
    {
      tool: "Notion",
      action: "Read your meeting notes and extract the action items",
      duration: "1.1s",
      riskLevel: "read",
      liveOutput: "→ 4 action items with owners found",
    },
    {
      tool: "HubSpot",
      action: "Find the matching records for each action item",
      duration: "0.9s",
      riskLevel: "read",
      liveOutput: "→ 3 of 4 records found",
    },
    {
      tool: "HubSpot",
      action: "Update each record with its action items and owner",
      duration: "1.4s",
      riskLevel: "modify",
      liveOutput: "→ ⚠ Bloom Health has no company record",
    },
  ],
  errorStep: {
    index: 2,
    what: "Couldn't update Bloom Health — no company record in HubSpot.",
    why: "Bloom Health is mentioned in your notes but has no company record in HubSpot.",
    fix:
      "Skip Bloom Health for now and update the other 3 records. You can create the Bloom Health company in HubSpot and re-run that update later.",
    fixShort: "Skip Bloom Health and update the other 3 records.",
    buttonLabel: "Skip Bloom & retry",
  },
  results: {
    title: "CRM records updated",
    summary:
      "Updated 3 HubSpot records with action items and owners from your meeting notes. Bloom Health was skipped (no company record).",
    metrics: [
      { value: "4", label: "action items" },
      { value: "3", label: "records updated" },
      { value: "1", label: "skipped (no record)" },
    ],
    outcomes: [
      {
        type: "document",
        count: 4,
        title: "action items extracted from notes",
        detail: "With owners, from your meeting notes.",
        link: "https://www.notion.so/aura-meeting-notes-88c2",
        linkLabel: "Open in Notion",
      },
      {
        type: "crm",
        count: 3,
        title: "HubSpot records updated",
        detail: "Companies updated with action items and owners.",
        link: "https://app.hubspot.com/companies",
        linkLabel: "View in HubSpot",
        items: [
          { label: "Acme Corp → Dana", detail: "Updated" },
          { label: "Northwind → Priya", detail: "Updated" },
          { label: "Globex → Sam", detail: "Updated" },
        ],
      },
      {
        type: "alert",
        count: 1,
        title: "company needs attention",
        detail: "Bloom Health has no HubSpot record.",
        attention: true,
        link: "https://app.hubspot.com/companies",
        linkLabel: "View issue",
      },
    ],
    nextSteps: [
      "Create the Bloom Health company in HubSpot and re-run",
      "Log this meeting's outcomes to the activity feed",
      "Schedule the next sync to update CRM automatically",
    ],
  },
};

// Task-driven "difficult connection" demo: the plan requires an internal tool
// ("Creator Approvals") that has no standard OAuth integration. AURA surfaces
// it in the plan's connection gate, routes the user through the AURA Interface
// learn flow (URL → analyze → discovered capabilities → allow & connect), then
// returns to the same plan with it connected. Clean run (no error step) so the
// connection innovation is the focus.
const creatorApprovalsMock = {
  plan: {
    interpretation:
      "Every Friday you want AURA to pull your sales from Salesforce, route any flagged creators through your internal approval tool, and post a summary to the team in Slack.",
    estimatedTime: "~11 seconds",
    workflowName: "Weekly creator approvals & summary",
    steps: [
      {
        tool: "Salesforce",
        title: "Get this week's sales results",
        iWill: "pull this week's sales results from Salesforce",
        action: "Get this week's sales results from Salesforce",
        detail: "",
        reason: "We need the sales data before we can flag creators.",
        output: "12 deals reviewed, 3 creators flagged",
        flow: [
          { label: "Uses", value: "Salesforce" },
          { label: "Creates", value: "12 deals reviewed, 3 creators flagged" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "list",
          title: "12 deals reviewed from Salesforce",
          summary: "Pulled 12 deals from Salesforce",
          previewLabel: "View deals",
          items: [
            { label: "Acme Corp", detail: "$48,000 · flagged for review" },
            { label: "Bloom Health", detail: "$31,500 · flagged for review" },
            { label: "Globex", detail: "$22,000 · flagged for review" },
            { label: "Northwind", detail: "$15,000 · cleared" },
            { label: "Initech", detail: "$12,000 · cleared" },
          ],
        },
      },
      {
        tool: "AURA Intelligence",
        title: "Flag creators needing approval",
        iWill: "flag the creators that need approval this week",
        action: "Flag the creators that need approval this week",
        detail: "",
        reason: "",
        output: "3 creators prepared for submission",
        flow: [
          { label: "Uses", value: "AURA Intelligence" },
          { label: "Creates", value: "3 creators prepared for submission" },
        ],
        riskLevel: "read",
        riskNote: "",
        preview: {
          type: "list",
          title: "3 creators flagged for approval",
          summary: "Flagged 3 creators for approval",
          previewLabel: "View flagged creators",
          items: [
            { label: "Acme Corp", detail: "Creator: Jordan Lee" },
            { label: "Bloom Health", detail: "Creator: Maya Patel" },
            { label: "Globex", detail: "Creator: Sam Rivera" },
          ],
        },
      },
      {
        tool: "Creator Approvals",
        title: "Submit flagged creators for approval",
        iWill: "submit each flagged creator through your internal approval tool",
        action: "Submit flagged creators through Creator Approvals",
        detail: "",
        reason: "",
        output: "3 creators submitted for approval",
        flow: [
          { label: "Uses", value: "Creator Approvals" },
          { label: "Creates", value: "3 creators submitted for approval" },
        ],
        riskLevel: "modify",
        riskNote: "You'll approve each submission before it's sent through the tool.",
        preview: {
          type: "list",
          title: "3 creators to submit through Creator Approvals",
          summary: "Submit 3 creators through Creator Approvals",
          previewNote: "Each submission waits for your approval",
          previewLabel: "Preview submissions",
          items: [
            { label: "Jordan Lee — Acme Corp", detail: "Creator + manager details ready" },
            { label: "Maya Patel — Bloom Health", detail: "Creator + manager details ready" },
            { label: "Sam Rivera — Globex", detail: "Creator + manager details ready" },
          ],
        },
      },
      {
        tool: "Slack",
        title: "Post the summary to the team",
        iWill: "post a summary of this week's approvals to the team in Slack",
        action: "Post a summary of this week's approvals to Slack",
        detail: "",
        reason: "",
        output: "a summary posted to #sales-ops",
        flow: [
          { label: "Uses", value: "Slack" },
          { label: "Creates", value: "a summary posted to #sales-ops" },
        ],
        riskLevel: "modify",
        riskNote: "You'll review the message before it's posted.",
        preview: {
          type: "email",
          to: "#sales-ops",
          summary: "Post summary to #sales-ops",
          previewNote: "#sales-ops",
          previewLabel: "Preview message",
          subject: "This week's creator approvals",
          body:
            "Weekly recap:\n\n• 12 deals reviewed in Salesforce\n• 3 creators flagged for approval\n• 3 submissions sent through Creator Approvals (all approved)\n\nNext Friday AURA will run this again automatically.",
        },
      },
    ],
  },
  execSteps: [
    {
      tool: "Salesforce",
      action: "Get this week's sales results from Salesforce",
      duration: "1.2s",
      riskLevel: "read",
      liveOutput: "→ 12 deals reviewed, 3 creators flagged",
      time: "10:02",
    },
    {
      tool: "AURA Intelligence",
      action: "Flag the creators that need approval this week",
      duration: "0.9s",
      riskLevel: "read",
      liveOutput: "→ 3 creators prepared for submission",
      time: "10:03",
    },
    {
      tool: "Creator Approvals",
      action: "Submit flagged creators through Creator Approvals",
      duration: "1.6s",
      riskLevel: "modify",
      liveOutput: "→ 3 creators submitted",
      time: "10:03",
      note: "You approved each submission",
    },
    {
      tool: "Slack",
      action: "Post a summary of this week's approvals to Slack",
      duration: "1.0s",
      riskLevel: "modify",
      liveOutput: "→ Summary posted to #sales-ops",
      time: "10:04",
    },
  ],
  results: {
    title: "Creators approved & summarized",
    summary:
      "Pulled this week's sales from Salesforce, submitted 3 flagged creators through Creator Approvals, and posted a summary to #sales-ops.",
    metrics: [
      { value: "12", label: "deals reviewed" },
      { value: "3", label: "creators submitted" },
      { value: "1", label: "summary posted" },
    ],
    outcomes: [
      {
        type: "crm",
        count: 12,
        title: "deals reviewed in Salesforce",
        detail: "This week's pipeline, 3 flagged for approval.",
        link: "https://acme.lightning.force.com/lightning/o/Opportunity/list",
        linkLabel: "Open in Salesforce",
      },
      {
        type: "approval",
        count: 3,
        title: "creators submitted through Creator Approvals",
        detail: "Connected via AURA Interface — each submission approved by you.",
        items: [
          { label: "Jordan Lee — Acme Corp", detail: "Submitted & approved" },
          { label: "Maya Patel — Bloom Health", detail: "Submitted & approved" },
          { label: "Sam Rivera — Globex", detail: "Submitted & approved" },
        ],
      },
      {
        type: "message",
        count: 1,
        title: "summary posted to Slack",
        detail: "Posted to #sales-ops.",
        link: "https://acme.slack.com/archives/C0SALESOPS",
        linkLabel: "Open in Slack",
      },
    ],
    nextSteps: [
      "Schedule this to run every Friday automatically",
      "Add marketing performance from Meta Ads to the summary",
      "Notify managers when a creator is submitted for approval",
    ],
  },
};

export const CAMPAIGN_MOCK = campaignMock;
export const FOLLOWUPS_MOCK = followupsMock;
export const JIRA_MOCK = jiraMock;
export const CRM_MOCK = crmMock;
export const CREATOR_APPROVALS_MOCK = creatorApprovalsMock;