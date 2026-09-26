import { promptToolHints } from "./promptToolHints.mjs";

const normalize = (value) => String(value || "")
  .replace(/\s+/g, " ")
  .trim();

const lower = (value) => normalize(value).toLowerCase();

const hasAny = (text, values) => values.some((value) => text.includes(value));

const TOOL_MENTIONS = {
  "Google Docs": ["google docs", "google doc"],
  "Google Calendar": ["google calendar", "calendar event"],
  "Google Sheets": ["google sheets", "google sheet", "spreadsheet"],
};

const ACTION_VERBS = /\b(read|find|check|list|search|get|add|book|create|delete|email|invite|post|publish|schedule|send|sync|update|write)\b/g;
const READ_VERBS = new Set(["read", "find", "check", "list", "search", "get"]);
const WRITE_AFTER_TOOL = /^\s*:\s*(add|book|create|delete|email|invite|post|publish|schedule|send|sync|update|write)\b/;

const writeIntentForTool = (text, tool) => {
  const mentions = TOOL_MENTIONS[tool] || [tool.toLowerCase()];
  for (const clause of text.split(/[;,.]/)) {
    for (const mention of mentions) {
      const position = clause.indexOf(mention);
      if (position < 0) continue;
      const verbs = [...clause.slice(0, position).matchAll(ACTION_VERBS)];
      if (verbs.length && !READ_VERBS.has(verbs.at(-1)[0])) return verbs.at(-1)[0];
      const after = clause.slice(position + mention.length).match(WRITE_AFTER_TOOL);
      if (after) return after[1];
    }
  }
  return null;
};

const TRANSFORM_WORDS = [
  "analyze", "compare", "draft", "extract", "prepare", "prioritize",
  "report", "summarize", "summary", "turn ",
];

function actionForTool(prompt, tool) {
  const text = lower(prompt);
  const name = tool.toLowerCase();
  const writeVerb = writeIntentForTool(text, tool);

  if (/weather|forecast/.test(name)) {
    return {
      title: "Check the weather",
      iWill: `get the requested forecast with ${tool}`,
      output: "Verified forecast data",
      riskLevel: "read",
    };
  }
  if (writeVerb) {
    const creation = {
      "Google Docs": { title: "Create the Google Doc", iWill: "prepare the requested document for creation", output: "Google Doc ready for review" },
      "Google Calendar": { title: "Schedule the calendar event", iWill: "prepare the requested event for creation", output: "Calendar event ready for review" },
      Canva: { title: "Create the Canva design", iWill: "prepare the requested design for creation", output: "Canva design ready for review" },
      Gmail: { title: "Send the email", iWill: "prepare the requested email for sending", output: "Email ready for review" },
    }[tool];
    const action = ["create", "write", "schedule", "book", "send", "email"].includes(writeVerb)
      ? creation : null;
    return {
      title: action?.title || `${writeVerb.charAt(0).toUpperCase()}${writeVerb.slice(1)} with ${tool}`,
      iWill: action?.iWill || `prepare the requested ${tool} change for review`,
      output: action?.output || `${tool} change ready for review`,
      riskLevel: "modify",
    };
  }
  const read = {
    "Google Docs": { title: "Read the relevant document", iWill: "read the Google Doc you specify", output: "Document content for the next step" },
    "Google Calendar": { title: "Check the calendar", iWill: "check the calendar events you specify", output: "Relevant calendar events" },
    Canva: { title: "Review the Canva design", iWill: "read the Canva design you specify", output: "Design content for the next step" },
    Gmail: { title: "Read the relevant email", iWill: "read the Gmail message you specify", output: "Email content for the next step" },
  }[tool];
  return {
    title: read?.title || `Read from ${tool}`,
    iWill: read?.iWill || `read the relevant information you specify in ${tool}`,
    output: read?.output || `Relevant information from ${tool}`,
    riskLevel: "read",
  };
}

function step(tool, details) {
  const modifies = details.riskLevel === "modify";
  return {
    tool,
    title: details.title,
    iWill: details.iWill,
    action: details.iWill.charAt(0).toUpperCase() + details.iWill.slice(1),
    detail: "AURA will confirm the exact items and changes before starting.",
    reason: details.iWill,
    output: details.output,
    flow: [
      { label: tool === "AURA Intelligence" ? "Uses" : "Uses", value: tool },
      { label: "Creates", value: details.output },
    ],
    riskLevel: details.riskLevel,
    riskNote: modifies ? "You'll review the exact change before AURA submits it." : "",
  };
}

function workflowName(prompt) {
  const words = normalize(prompt)
    .replace(/[^a-zA-Z0-9\s-]/g, "")
    .split(" ")
    .filter(Boolean)
    .slice(0, 6);
  return words.length ? words.join(" ") : "Complete workflow";
}

/**
 * Produce a useful plan immediately, before connector discovery or executable
 * action compilation. A single language-model call may refine this draft, but
 * the user never has to stare at a loader while that work happens.
 */
export function instantLanguagePlan(prompt = "", catalog = [], selectedTools = []) {
  const intent = normalize(prompt) || "Complete the requested workflow";
  const hinted = promptToolHints(intent, catalog, 8);
  const tools = [...new Set([...selectedTools, ...hinted].filter(Boolean))];
  const steps = tools.map((tool) => step(tool, actionForTool(intent, tool)));
  const text = lower(intent);

  if (hasAny(text, TRANSFORM_WORDS)) {
    const transform = step("AURA Intelligence", {
      title: /summari[sz]|summary/.test(text) ? "Prepare the summary" : "Prepare the result",
      iWill: /summari[sz]|summary/.test(text)
        ? "summarize the source information for the requested outcome"
        : "transform the source information into the requested result",
      output: /summari[sz]|summary/.test(text) ? "Prepared summary" : "Prepared result",
      riskLevel: "read",
    });
    const writeIndex = steps.findIndex((item) => item.riskLevel === "modify");
    steps.splice(writeIndex >= 0 ? writeIndex : steps.length, 0, transform);
  }

  if (!steps.length) {
    steps.push(
      step("AURA Intelligence", {
        title: "Understand the request",
        iWill: "identify the goal, source information, constraints and desired result",
        output: "Structured task requirements",
        riskLevel: "read",
      }),
      step("AURA Intelligence", {
        title: "Prepare the result",
        iWill: "complete the requested work from the available information",
        output: "Result ready for review",
        riskLevel: "read",
      }),
    );
  }

  return {
    workflowName: workflowName(intent),
    interpretation: intent,
    estimatedTime: "Preparing the executable plan",
    steps,
    provisional: true,
    compileState: "validating",
  };
}

export function languageDraftPrompt(intent = "", selectedTools = [], revision = "", currentSteps = []) {
  const preferred = selectedTools.length
    ? `The user explicitly selected these tools: ${selectedTools.join(", ")}. Use them when relevant.`
    : "";
  const revisionContext = revision
    ? `Latest requested change: "${normalize(revision)}"\nPrevious steps: ${currentSteps.map((item) => item.title || item.reason || item.operation || "").join("; ")}\nThe latest change overrides earlier provider choices. Remove any provider the user replaced.`
    : "";
  return `You are AURA. Turn the user's request into a short, plain-language workflow plan.

User request: "${normalize(intent)}"
${preferred}
${revisionContext}

This is a language-only planning pass. Do not check connections, OAuth, APIs, action schemas, or whether a provider is currently released. A missing connection must never prevent the plan from being written.

Return 2-6 ordered steps. Preserve every provider the user explicitly names unless a later instruction replaces it. Add an AURA Intelligence step for reasoning, summarizing, comparing, drafting, or transforming data. Use provider names for external steps and "AURA Intelligence" for internal reasoning.

Each step needs: title, iWill, action, reason, output, flow, riskLevel, and riskNote. Use riskLevel "modify" for sending, posting, creating, deleting, scheduling, or updating; otherwise use "read". Tell the user they will review consequential changes. Keep wording concise and non-technical. Never claim that data has already been fetched or an action has already happened.`;
}
