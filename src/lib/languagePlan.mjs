import { promptToolHints } from "./promptToolHints.mjs";

const normalize = (value) => String(value || "")
  .replace(/\s+/g, " ")
  .trim();

const lower = (value) => normalize(value).toLowerCase();

const hasAny = (text, values) => values.some((value) => text.includes(value));

const WRITE_WORDS = [
  "add ", "book ", "create ", "delete ", "email ", "invite ", "post ",
  "publish ", "schedule ", "send ", "sync ", "update ", "write ",
];

const TRANSFORM_WORDS = [
  "analyze", "compare", "draft", "extract", "prepare", "prioritize",
  "report", "summarize", "summary", "turn ",
];

function actionForTool(prompt, tool, index, tools) {
  const text = lower(prompt);
  const name = tool.toLowerCase();
  const position = text.indexOf(name);
  const context = position >= 0
    ? text.slice(Math.max(0, position - 80), Math.min(text.length, position + name.length + 80))
    : text;
  const isLast = index === tools.length - 1;
  const writes = hasAny(context, WRITE_WORDS) && (isLast || tools.length === 1);

  if (/weather|forecast/.test(name)) {
    return {
      title: "Check the weather",
      iWill: `get the requested forecast with ${tool}`,
      output: "Verified forecast data",
      riskLevel: "read",
    };
  }
  if (writes) {
    return {
      title: `Update ${tool}`,
      iWill: `prepare the requested change in ${tool}`,
      output: `${tool} update ready for review`,
      riskLevel: "modify",
    };
  }
  return {
    title: `Get ${tool} data`,
    iWill: `read the information needed from ${tool}`,
    output: `${tool} source data`,
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
    detail: "Exact fields and provider actions are being validated backstage.",
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
  const steps = tools.map((tool, index) => step(tool, actionForTool(intent, tool, index, tools)));
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
    estimatedTime: "Plan ready — validating executable details backstage",
    steps,
    provisional: true,
    compileState: "validating",
  };
}

export function languageDraftPrompt(intent = "", selectedTools = []) {
  const preferred = selectedTools.length
    ? `The user explicitly selected these tools: ${selectedTools.join(", ")}. Use them when relevant.`
    : "";
  return `You are AURA. Turn the user's request into a short, plain-language workflow plan.

User request: "${normalize(intent)}"
${preferred}

This is a language-only planning pass. Do not check connections, OAuth, APIs, action schemas, or whether a provider is currently released. A missing connection must never prevent the plan from being written.

Return 2-6 ordered steps. Preserve every provider the user explicitly names. Add an AURA Intelligence step for reasoning, summarizing, comparing, drafting, or transforming data. Use provider names for external steps and "AURA Intelligence" for internal reasoning.

Each step needs: title, iWill, action, reason, output, flow, riskLevel, and riskNote. Use riskLevel "modify" for sending, posting, creating, deleting, scheduling, or updating; otherwise use "read". Tell the user they will review consequential changes. Keep wording concise and non-technical. Never claim that data has already been fetched or an action has already happened.`;
}

