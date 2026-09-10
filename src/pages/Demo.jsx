import { useState, useCallback, useRef, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { aura } from "@/api/auraClient";
import { WORKFLOW_EXAMPLES } from "@/lib/demoData";
import { CREATOR_APPROVALS_MOCK } from "@/lib/mockWorkflows";
import TopBar from "@/components/aura/TopBar";
import CommandInput from "@/components/aura/CommandInput";
import ConfirmView from "@/components/aura/ConfirmView";
import PlanView from "@/components/aura/PlanView";
import PreviewView from "@/components/aura/PreviewView";
import ExecutionView from "@/components/aura/ExecutionView";
import ErrorView from "@/components/aura/ErrorView";
import ResultsView from "@/components/aura/ResultsView";
import AmbientBackground from "@/components/aura/AmbientBackground";
import HistoryPanel from "@/components/aura/HistoryPanel";
import EditRunReviewModal from "@/components/aura/EditRunReviewModal";
import { detectNewConsequential } from "@/lib/editRunDetect";
import { requestNotifyPermission, notifyWorkflowComplete, notifyWorkflowError } from "@/lib/auraNotify";
import { connectTool, hydrateConnections } from "@/lib/connectService";
import { getAllConnections } from "@/lib/connectionsStore";
import { CATALOG } from "@/lib/toolCatalog";
import {
  approvePythonPlan,
  cancelPythonRun,
  createPythonRun,
  decidePythonApproval,
  forgetActivePythonRun,
  getPythonRun,
  resumePythonRun,
  resumePythonRunAfterConnection,
} from "@/lib/auraApi";

import {
  alternativeRecoveryPrompt,
  needsRecovery,
  recoveryForRun,
} from "@/lib/runRecovery.mjs";
import {
  planningConnectionRequirements,
  planningDisposition,
  promptConnectionRequirements,
} from "@/lib/planningFlow.mjs";
import { hasDurablePlan, planningRequestPrompt } from "@/lib/runtimePlan.mjs";

const STEP_DURATION = 2.6;

const planToolName = (step) => {
  if (step.tool_slug === "google") {
    if (step.operation.startsWith("gmail.")) return "Gmail";
    if (step.operation.startsWith("calendar.")) return "Google Calendar";
    if (step.operation.startsWith("sheets.")) return "Google Sheets";
    return "Google Drive";
  }
  const names = {
    aura: "AURA Intelligence",
    apify: "Apify",
    airtable: "Airtable",
    notion: "Notion",
    mailchimp: "Mailchimp",
    canva: "Canva",
    tiktok: "TikTok",
    slack: "Slack",
    hubspot: "HubSpot",
    salesforce: "Salesforce",
    clickup: "ClickUp",
    jira: "Jira",
    confluence: "Confluence",
    "meta-ads": "Meta Ads",
    instagram: "Instagram",
    linkedin: "LinkedIn",
    figma: "Figma",
    shopify: "Shopify",
    stripe: "Stripe",
    quickbooks: "QuickBooks",
    pinterest: "Pinterest",
    modash: "Modash",
    hypeauditor: "HypeAuditor",
    "creator-approvals": "Creator Approvals",
  };
  return names[step.tool_slug] || step.tool_slug;
};

const cleanSentence = (value, fallback = "Complete this step") => {
  const text = String(value || fallback)
    .replace(/^i(?:'|’)ll\s+/i, "")
    .replace(/[.\s]+$/, "")
    .trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : fallback;
};

const firstPersonStepCopy = (value, fallback = "complete this step") => {
  const text = String(value || fallback)
    .replace(/^aura\s+will\s+/i, "")
    .replace(/^i(?:'|’)ll\s+/i, "")
    .replace(/[.\s]+$/, "")
    .trim();
  const verbForms = {
    checks: "check",
    collects: "collect",
    creates: "create",
    delivers: "deliver",
    fetches: "fetch",
    finds: "find",
    gets: "get",
    identifies: "identify",
    inspects: "inspect",
    lists: "list",
    locates: "locate",
    posts: "post",
    reads: "read",
    retrieves: "retrieve",
    sends: "send",
    updates: "update",
  };
  return text.replace(/^([A-Za-z]+)/, (word) => verbForms[word.toLowerCase()] || word.toLowerCase());
};

const friendlyStepTitle = (step) => {
  const tool = planToolName(step);
  const reason = String(step.reason || "").toLowerCase();
  const operation = String(step.operation || "");

  if (operation === "weather.forecast") return "Check tomorrow's weather";
  if (operation === "gmail.send") return "Send the email";
  if (operation.startsWith("gmail.")) return "Review email context";
  if (operation.startsWith("calendar.")) return operation.includes("create") ? "Schedule the event" : "Check the calendar";
  if (operation.startsWith("sheets.")) return operation.includes("update") || operation.includes("append") ? "Update the spreadsheet" : "Read the spreadsheet";
  if (operation.startsWith("hubspot.")) return reason.includes("update") ? "Update HubSpot records" : "Find HubSpot records";
  if (operation === "notion.search") return "Find the Notion notes";
  if (operation.startsWith("notion.page.get") || operation.startsWith("notion.blocks.children.list")) return "Read the Notion notes";
  if (operation.startsWith("notion.page.create")) return "Create the Notion page";
  if (operation.startsWith("notion.page.update") || operation.startsWith("notion.blocks.children.append")) return "Update the Notion page";
  if (operation === "jira.projects.list") return "Find the Jira project";
  if (operation === "jira.issues.search") return "Find Jira issues";
  if (operation === "jira.issue.get") return "Read the Jira issue";
  if (operation === "jira.issue.create") return "Create the Jira tasks";
  if (operation === "jira.issue.update") return "Update the Jira task";
  if (/find|identify|determine|search|match/.test(reason)) return "Find matching records";
  if (/get|pull|fetch|read|collect/.test(reason)) return `Get ${tool} data`;
  if (/transform|compile|summari[sz]e|breakdown|report/.test(reason)) return "Prepare the report";
  if (/draft|write|compose/.test(reason)) return "Draft the content";
  if (/send|deliver|notify|post/.test(reason)) return `Send with ${tool}`;
  if (/update|change|sync/.test(reason)) return `Update ${tool}`;
  if (/create|add/.test(reason)) return `Create in ${tool}`;
  return `Use ${tool}`;
};

const resultLinkFromOutputs = (outputs = []) => {
  for (const output of [...outputs].reverse()) {
    const url = output?.provider_result?.result_url;
    if (typeof url === "string" && url.startsWith("https://")) return url;
  }
  return null;
};

const resolvedPreviewStep = (planned, runtime) => {
  if (!runtime?.consequential) return planned;
  if (runtime.approval_status !== "pending" || runtime.approval_preview?.status !== "ready") {
    return { ...planned, riskLevel: "read", preview: undefined, approvalPending: true };
  }
  const args = runtime.approval_preview.arguments;
  let preview;
  if (runtime.operation === "gmail.send") {
    preview = {
      type: "email",
      to: args.to || "me",
      subject: args.subject || "",
      body: args.body || "",
      note: "Prepared from the completed workflow steps.",
    };
  } else if (runtime.operation.startsWith("jira.issue.")) {
    preview = {
      type: "jira",
      title: runtime.operation === "jira.issue.create" ? "Jira task preview" : "Jira update preview",
      project: args.project_key || args.projectKey || args.project || "",
      summary: args.summary || "",
      description: args.description || "",
      assignee: args.assignee_id || args.assignee || "",
    };
  } else {
    preview = {
      type: "list",
      title: `${planToolName(runtime)} change preview`,
      items: Object.entries(args).map(([label, value]) => ({
        label,
        detail: typeof value === "string" ? value : JSON.stringify(value),
      })),
    };
  }
  return {
    ...planned,
    riskLevel: "modify",
    arguments: args,
    resolvedArguments: args,
    approvalId: runtime.approval_id,
    preview,
  };
};

const editedArgumentsForStep = (step) => {
  const args = { ...(step.resolvedArguments || step.arguments || {}) };
  const preview = step.preview || {};
  if (preview.type === "email") {
    return { ...args, to: preview.to, subject: preview.subject, body: preview.body };
  }
  if (preview.type === "jira") {
    return {
      ...args,
      project_key: preview.project,
      summary: preview.summary,
      description: preview.description,
      assignee_id: preview.assignee,
    };
  }
  return args;
};

const uiPlanFromRun = (run) => ({
  workflowName: run.plan?.name || "Saved workflow",
  interpretation: run.plan?.interpretation || run.prompt,
  estimatedTime: run.plan?.planning_artifacts?.timings_ms?.total
    ? `Planned in ${(run.plan.planning_artifacts.timings_ms.total / 1000).toFixed(1)}s`
    : "Runs durably in the AURA control plane",
  steps: (run.plan?.steps || []).map((step) => ({
    tool: planToolName(step),
    title: friendlyStepTitle(step),
    iWill: firstPersonStepCopy(step.reason),
    action: cleanSentence(step.reason),
    detail: JSON.stringify(step.arguments, null, 2),
    reason: step.reason,
    output: step.expected_output,
    flow: [
      { label: "Uses", value: planToolName(step) },
      { label: "Creates", value: step.expected_output },
    ],
    riskLevel: step.consequential ? "modify" : "read",
    riskNote: step.consequential ? "AURA will prepare the exact action and ask before submitting it." : "",
    preview: step.consequential ? {
      type: step.operation === "gmail.send" ? "email" : "list",
      to: step.arguments?.to || "",
      subject: step.arguments?.subject || "",
      body: step.arguments?.body || "",
      title: step.operation,
      items: Object.entries(step.arguments || {}).map(([label, value]) => ({
        label,
        detail: JSON.stringify(value),
      })),
    } : undefined,
  })),
});

const uiConnectionPlanFromRun = (run, interpretation) => ({
  workflowName: "",
  interpretation: run.plan?.interpretation || interpretation || run.prompt,
  estimatedTime: "Planning resumes after the connection is verified",
  steps: [],
  connectionRequirements: planningConnectionRequirements(run),
});

const INTERPRETATION_SCHEMA = {
  type: "object",
  properties: {
    interpretation: { type: "string" },
  },
};

const PLAN_SCHEMA = {
  type: "object",
  properties: {
    interpretation: { type: "string" },
    workflowName: { type: "string" },
    estimatedTime: { type: "string" },
    steps: {
      type: "array",
      items: {
        type: "object",
        properties: {
          tool: { type: "string" },
          title: { type: "string" },
          iWill: { type: "string" },
          action: { type: "string" },
          detail: { type: "string" },
          reason: { type: "string" },
          output: { type: "string" },
          flow: {
            type: "array",
            items: {
              type: "object",
              properties: {
                label: { type: "string" },
                value: { type: "string" },
              },
            },
          },
          riskLevel: { type: "string", enum: ["read", "modify"] },
          riskNote: { type: "string" },
          preview: {
            type: "object",
            properties: {
              type: { type: "string", enum: ["email", "table", "list", "document"] },
              summary: { type: "string" },
              to: { type: "string" },
              subject: { type: "string" },
              body: { type: "string" },
              note: { type: "string" },
              title: { type: "string" },
              columns: { type: "array", items: { type: "string" } },
              rows: { type: "array", items: { type: "array", items: { type: "string" } } },
              previewNote: { type: "string" },
              docTitle: { type: "string", description: "Title of the filled-out document" },
              docBody: { type: "string", description: "The full filled-out document body text — actual prose, not field labels" },
              items: {
                type: "array",
                items: {
                  type: "object",
                  properties: { label: { type: "string" }, detail: { type: "string" } },
                },
              },
            },
          },
        },
      },
    },
  },
};

const RESULTS_SCHEMA = {
  type: "object",
  properties: {
    title: { type: "string" },
    summary: { type: "string" },
    metrics: {
      type: "array",
      items: {
        type: "object",
        properties: { value: { type: "string" }, label: { type: "string" } },
      },
    },
    outcomes: {
      type: "array",
      items: {
        type: "object",
        properties: {
          type: { type: "string" },
          count: { type: "number" },
          title: { type: "string" },
          detail: { type: "string" },
          attention: { type: "boolean" },
          link: { type: "string" },
          linkLabel: { type: "string" },
          items: {
            type: "array",
            items: {
              type: "object",
              properties: {
                label: { type: "string" },
                detail: { type: "string" },
              },
            },
          },
        },
      },
    },
    nextSteps: { type: "array", items: { type: "string" } },
    breakdown: {
      type: "object",
      properties: {
        title: { type: "string" },
        columns: { type: "array", items: { type: "string" } },
        rows: { type: "array", items: { type: "array", items: { type: "string" } } },
        footnote: { type: "string" },
      },
    },
  },
};

export default function Demo() {
  const [phase, setPhase] = useState("input");
  const [originalPrompt, setOriginalPrompt] = useState("");
  const [interpretation, setInterpretation] = useState("");
  const [interpretationLoading, setInterpretationLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const [plan, setPlan] = useState(null);
  const [results, setResults] = useState(null);
  const [recoveryRun, setRecoveryRun] = useState(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryMessage, setRecoveryMessage] = useState("");
  const recoveryPendingRef = useRef(false);
  const [execSteps, setExecSteps] = useState([]);
  const [currentStepIdx, setCurrentStepIdx] = useState(0);
  const [approvedSteps, setApprovedSteps] = useState([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [startTime, setStartTime] = useState(null);
  const [workflowName, setWorkflowName] = useState("");
  const [editRun, setEditRun] = useState(null);
  const [editReviewOpen, setEditReviewOpen] = useState(false);
  const [editApproval, setEditApproval] = useState("writes");
  const [editFlag, setEditFlag] = useState(null);
  const [editRunMode, setEditRunMode] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  const editOriginalStepsRef = useRef([]);
  const attachedResourcesRef = useRef(null);
  const userSelectedToolsRef = useRef([]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const provider = params.get("tool_connected") || params.get("oauth_provider");
    const status = params.get("oauth_status") || (params.has("tool_connected") ? "success" : null);
    if (!provider || !status || !window.opener) return;
    window.opener.postMessage(
      {
        source: "aura-oauth",
        provider,
        status,
        message: params.get("oauth_message") || undefined,
      },
      window.location.origin
    );
    window.close();
  }, []);

  const timeoutRefs = useRef([]);
  const pendingMock = useRef(null);
  const resolvedErrorRef = useRef(false);
  const approvedStepsRef = useRef([]);
  const execTemplateRef = useRef([]);
  const originalPromptRef = useRef("");
  const currentRunIdRef = useRef(null);
  const currentWorkflowIdRef = useRef(null);
  const pythonRunIdRef = useRef(null);
  const pythonPlanRef = useRef(null);
  const pythonPollGenerationRef = useRef(0);
  const runRequestKeyRef = useRef(null);

  const clearTimeouts = () => {
    timeoutRefs.current.forEach(clearTimeout);
    timeoutRefs.current = [];
  };
  const pushT = (t) => timeoutRefs.current.push(t);

  const getPythonRunResilient = async (runId, generation, maxTransientFailures = 6) => {
    let transientFailures = 0;
    while (pythonPollGenerationRef.current === generation) {
      try {
        return await getPythonRun(runId);
      } catch (error) {
        const transient = !error.status || error.status === 429 || error.status >= 500;
        if (!transient) throw error;
        transientFailures += 1;
        if (transientFailures >= maxTransientFailures) throw error;
        const delay = Math.min(15000, 1000 * (2 ** Math.min(transientFailures - 1, 4)));
        await new Promise((resolve) => window.setTimeout(resolve, delay));
      }
    }
    return null;
  };

  const reset = useCallback(() => {
    clearTimeouts();
    pythonPollGenerationRef.current += 1;
    runRequestKeyRef.current = null;
    pendingMock.current = null;
    resolvedErrorRef.current = false;
    approvedStepsRef.current = [];
    setApprovedSteps([]);
    execTemplateRef.current = [];
    currentRunIdRef.current = null;
    currentWorkflowIdRef.current = null;
    pythonRunIdRef.current = null;
    pythonPlanRef.current = null;
    setPhase("input");
    setOriginalPrompt("");
    setInterpretation("");
    setPlan(null);
    setResults(null);
    setRecoveryRun(null);
    setRecoveryBusy(false);
    setRecoveryMessage("");
    setExecSteps([]);
    setCurrentStepIdx(0);
    setStartTime(null);
    setWorkflowName("");
    setEditRunMode(false);
    setAutoApprove(false);
    editOriginalStepsRef.current = [];
    userSelectedToolsRef.current = [];
  }, []);

  const handlePageBack = useCallback(() => {
    if (phase === "confirm") reset();
    else if (phase === "plan") setPhase("confirm");
    else if (phase === "preview") setPhase("plan");
    else if (phase === "executing" || phase === "error") setPhase("plan");
    else if (phase === "results") reset();
  }, [phase, reset]);

  // ---- Submit (input) ----
  const handleSubmit = useCallback((prompt, pinnedTools = [], resources = null, mock = null) => {
    clearTimeouts();
    requestNotifyPermission();
    setOriginalPrompt(prompt);
    originalPromptRef.current = prompt;
    attachedResourcesRef.current = resources;
    userSelectedToolsRef.current = (resources && resources.tools) || pinnedTools || [];
    resolvedErrorRef.current = false;

    if (mock) {
      pendingMock.current = mock;
      setInterpretation(mock.plan.interpretation);
      setPhase("confirm");
      return;
    }

    // Confirmation is deliberately local and instant. The Python planner performs
    // intent understanding once after the user confirms or edits this text.
    setPhase("confirm");
    setInterpretation(prompt);
    setInterpretationLoading(false);
  }, []);

  const startAlternativePlan = useCallback((run, userApproach = "") => {
    if (!run) return;
    const prompt = alternativeRecoveryPrompt(run, userApproach);
    reset();
    window.setTimeout(() => handleSubmit(prompt), 0);
  }, [handleSubmit, reset]);

  const handlePickExample = useCallback(
    (i) => {
      const ex = WORKFLOW_EXAMPLES[i];
      const mock = null;
      handleSubmit(ex.prompt, [], null, mock);
    },
    [handleSubmit]
  );

  // Ask AURA to re-interpret the same request from a different angle
  const handleRegenerateInterpretation = useCallback(() => {
    setInterpretationLoading(true);
    aura.integrations.Core
      .InvokeLLM({
        prompt: `You are AURA, an AI workflow automation platform. A user wants to automate a workflow.

Original request: "${originalPromptRef.current}"
Previous interpretation (they want a different one): "${interpretation}"

Write ONE clear, conversational sentence restating what they want — but offer a meaningfully DIFFERENT interpretation or angle than the previous one (e.g. a different scope, output, or approach that still fits the request). Plain, specific business language, warm tone.`,
        response_json_schema: INTERPRETATION_SCHEMA,
      })
      .then((res) => {
        setInterpretation(res.interpretation || "");
        setInterpretationLoading(false);
      })
      .catch(() => {
        setInterpretationLoading(false);
      });
  }, [interpretation]);

  // ---- Confirm interpretation ----
  const handleConfirm = useCallback(
    (editedInterpretation, revisionInstruction = "", allowLegacyPlanner = false) => {
      setInterpretation(editedInterpretation);
      if (!allowLegacyPlanner) {
        setPlanLoading(true);
        setPhase("plan");
        return (async () => {
          try {
            if (revisionInstruction) {
              const previousRunId = pythonRunIdRef.current;
              pythonPollGenerationRef.current += 1;
              runRequestKeyRef.current = null;
              pythonRunIdRef.current = null;
              pythonPlanRef.current = null;
              if (previousRunId) {
                await cancelPythonRun(previousRunId).catch(() => {});
                forgetActivePythonRun(previousRunId);
              }
            }
            const confirmedIntent = editedInterpretation.trim() || originalPromptRef.current;
            const planningPrompt = planningRequestPrompt(confirmedIntent, revisionInstruction);
            runRequestKeyRef.current ||= globalThis.crypto?.randomUUID?.()
              || `aura-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const resources = attachedResourcesRef.current || {};
            const created = await createPythonRun(planningPrompt, currentWorkflowIdRef.current, runRequestKeyRef.current, {
              requested_tools: userSelectedToolsRef.current,
              attached_documents: (resources.documents || []).map(({ name, file_url, size }) => ({
                name,
                file_url,
                size,
              })),
            });
            pythonRunIdRef.current = created.id;
            const generation = ++pythonPollGenerationRef.current;
            const planningDeadline = Date.now() + 90000;
            let run;
            for (;;) {
              run = await getPythonRunResilient(created.id, generation);
              if (!run) return;
              const disposition = planningDisposition(run);
              if (disposition === "review") break;
              if (disposition === "connection") {
                setPlan(uiConnectionPlanFromRun(run, editedInterpretation));
                return;
              }
              if (disposition === "unavailable") throw new Error(
                run.error || "The execution backend needs more setup before it can build this plan."
              );
              if (Date.now() >= planningDeadline) {
                throw new Error("Planning is taking longer than expected. The saved run remains safe to retry.");
              }
              await new Promise((resolve) => setTimeout(resolve, 1000));
            }
            pythonPlanRef.current = run.plan;
            setPlan(uiPlanFromRun(run));
          } catch (error) {
            console.warn("Python planning unavailable; no executable plan was created", error);
            if (pythonRunIdRef.current) forgetActivePythonRun(pythonRunIdRef.current);
            pythonRunIdRef.current = null;
            pythonPlanRef.current = null;
            runRequestKeyRef.current = null;
            const explicitRequirements = promptConnectionRequirements(
              editedInterpretation || originalPromptRef.current,
              CATALOG.map((tool) => ({
                ...tool,
                slug: tool.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
              })),
              getAllConnections()
            );
            setPlan(explicitRequirements.length
              ? {
                interpretation: editedInterpretation,
                workflowName: "",
                estimatedTime: "Planning resumes after the connection is verified",
                steps: [],
                connectionRequirements: explicitRequirements,
              }
              : {
                interpretation: editedInterpretation,
                workflowName: "",
                estimatedTime: "",
                steps: [],
                error: error?.message || "AURA couldn't build the plan right now.",
              });
          } finally {
            setPlanLoading(false);
          }
        })();
      }

      const mock = pendingMock.current;
      if (mock) {
        setPlan({ ...mock.plan, interpretation: editedInterpretation });
        setPhase("plan");
        return;
      }

      // Custom: generate the full plan
      setPlanLoading(true);
      setPhase("plan");
      const attachedPlanDocs = (attachedResourcesRef.current?.documents) || [];
      aura.integrations.Core
        .InvokeLLM({
          prompt: `You are AURA, an AI workflow automation platform. Build an execution plan for this workflow.

Confirmed intent: "${editedInterpretation}"
Original request: "${originalPromptRef.current}"

${
  (() => {
    const r = attachedResourcesRef.current;
    if (!r) return "";
    const parts = [];
    if (r.tools && r.tools.length) parts.push(`Tools the user already connected and wants used: ${r.tools.join(", ")}.`);
    if (r.documents && r.documents.length) parts.push(`Documents the user attached for this workflow: ${r.documents.map((d) => d.name).join(", ")}. Read their contents — use the real data from these files as the source data where relevant, and reflect specifics from the files in the plan steps and previews.`);
    return parts.length ? `\nThe user provided these resources — prefer them in the plan:\n${parts.join("\n")}\n` : "";
  })()
}
${
  (() => {
    const map = getAllConnections();
    const connected = Object.keys(map).filter((k) => map[k] && k !== "AURA Intelligence");
    if (!connected.length) return "";
    return `\nTools the user has already connected to AURA (prefer these when they fit the job): ${connected.join(", ")}.\n`;
  })()
}
Tool selection — YOU decide which tools to use:
- MANDATORY SPECIALIZED TOOLS: some jobs require a specialized data API — never substitute a weaker generic tool (no "TikTok API", no "AURA Intelligence", no web search) for these:
  - ANY step that finds/discovers/searches TikTok or Instagram creators, influencers, or creator stats (followers, engagement, contact emails) → the "tool" MUST be "Modash" (or "HypeAuditor"). This is non-negotiable: verified creator stats only come from a creator-data API. If it's not connected, still name "Modash" as the tool and set "riskNote" to: "Without a connected creator-data API (Modash), discovery results are unverified LLM estimates."
  - ANY step that scrapes or verifies a public profile → the "tool" MUST be "Apify".
- For each step, pick the BEST tool for that specific job. When more than one tool could work, choose the one that fits most naturally (right capability, least friction) — and prefer a tool the user has already connected when it's a good fit.
- If the ideal tool isn't connected, still propose it — the user will be prompted to connect it, and can swap it for another tool afterwards.
- The user can change any tool choice later in the plan, so don't hedge — commit to the best pick and name it in "tool", "action", and the "Uses"/"Creates" flow.
- Be honest about quality: if the best tool for a step isn't connected, say so in "riskNote" rather than silently substituting a weaker tool. Never present LLM-generated guesses as verified data.

Rules:
- "interpretation": ONE clear action sentence stating exactly what this workflow does when run — naming the key tools and the outcome (e.g. "Sync customer and project information across HubSpot, Notion and Jira, then notify the team"). Imperative, action-oriented. NOT a description of the user's problem or marketing copy.
- "title": a SHORT 2-4 word imperative title for the step (e.g. "Get campaign performance").
- "iWill": what AURA will do, in plain language, lowercase, NO "I'll" prefix (e.g. "pull this week's campaign performance from Meta Ads"). Do NOT lead with API calls, JSON or object mappings.
- "action": a plain BUSINESS language description of the step (e.g. "Get this week's campaign performance from Meta Ads").
- Put technical specifics (API names, fields, transformations) in "detail" — hidden from the default view.
- "flow": 1-2 entries. Each has "label" (ONLY "Uses" or "Creates") and "value". "Uses" = the tool/data this step reads; "Creates" = the result or destination it produces. This makes the data flow visible to the user.
- "riskLevel": "read" for read-only steps (fetching, scoring, compiling, drafting). "modify" for anything that sends, creates, updates, deletes, posts, or schedules.
- "riskNote": for modify steps, a short line telling the user they'll review it before it happens (e.g. "You'll review the emails before they're sent."). Empty string for read steps.
- "preview": REQUIRED for every "modify" step — a concrete preview of exactly what will be sent/changed so the user can approve it. THE PREVIEW MUST MATCH THE STEP'S ACTUAL TOOL AND ACTION — never default to an email preview for a step that is NOT an email step.
  - If the step sends an email (tool/action is Gmail/email/notify): type "email" with to/subject/body.
  - If the step writes rows/records to a sheet, CRM, or database (tool/action is Google Sheets, Airtable, HubSpot, Salesforce, etc.): type "table" with title/columns/rows (3-6 realistic sample rows matching that tool's data).
  - If the step fills, drafts, or updates a document (tool/action is Google Docs, Notion, "fill out", "draft a doc", "write to doc", "create a document draft"): type "document" with docTitle (the document's title) and docBody (the FULL filled-out document body as actual prose — real paragraphs of text that would appear in the document, incorporating specifics from the confirmed intent and any attached source files. NOT field labels or key-value pairs — actual document content the reader would see). If the user attached a document file, base the filled content on that document's structure and fill in the real values.
  - If the step creates tasks/records/tickets (Jira, Notion tasks, etc.): type "list" with title/items.
  - Never use type "email" for a step that does not send an email. If unsure which type fits, use "list".
  - Fill with realistic content reflecting the confirmed intent and THIS step's specific action — the preview must read as a direct illustration of what the step does, not a generic template.
- Use realistic business tools (Slack, HubSpot, Gmail, Salesforce, Meta Ads, Google Sheets, Notion, Jira, Google Calendar, Stripe).
- SPECIALIZED DATA TOOLS — propose the right specialized API when a step needs verified data that only it can provide. Do NOT silently substitute a weaker generic tool:
  - Discovering/finding creators or influencers with verified follower counts, engagement, or contact emails → propose "Modash" (or "HypeAuditor"). These are the ONLY way to get verified creator stats. If neither is connected, STILL propose one by name (the user will be prompted to connect it with an API key), and set the step's "riskNote" to: "Without a connected creator-data API (Modash), discovery results are unverified LLM estimates."
  - Scraping or verifying a public profile → propose "Apify".
- Be honest about quality: if the best tool for a step isn't connected, say so in "riskNote" rather than silently substituting a weaker tool. Never present LLM-generated guesses as verified data.
- "workflowName": a SHORT reusable job title (2-6 words, imperative) naming the recurring workflow itself — e.g. "Sync customer project across apps", "Route new leads to sales". NOT an outcome of one run (never past-tense like "Project synchronized"). This names the saved workflow, not an individual run.
- Generate 3-5 steps. estimatedTime e.g. "~10 seconds".`,
          response_json_schema: PLAN_SCHEMA,
          file_urls: attachedPlanDocs.map((d) => d.file_url).filter(Boolean),
        })
        .then((res) => {
          setPlan(res);
          setPlanLoading(false);
        })
        .catch(() => {
          setPlan({
            interpretation: editedInterpretation,
            estimatedTime: "~8 seconds",
            steps: [
              {
                tool: "AURA Intelligence",
                action: "Analyze your request and prepare the workflow",
                detail: "",
                reason: "AURA needs to understand the request before acting.",
                output: "A workflow plan",
                riskLevel: "read",
                riskNote: "",
              },
            ],
          });
          setPlanLoading(false);
        });
    },
    []
  );

  const handlePlanRevision = useCallback(
    (instruction) => handleConfirm(interpretation, instruction),
    [handleConfirm, interpretation]
  );

  const handleRetryPlanning = useCallback(() => {
    const failedRunId = pythonRunIdRef.current;
    if (failedRunId) forgetActivePythonRun(failedRunId);
    pythonRunIdRef.current = null;
    pythonPlanRef.current = null;
    runRequestKeyRef.current = null;
    return handleConfirm(interpretation);
  }, [handleConfirm, interpretation]);

  const handlePlanningConnectionRecovered = async (_toolName, connectionId) => {
    const runId = pythonRunIdRef.current;
    if (!runId || !connectionId) return handleRetryPlanning();
    setPlanLoading(true);
    try {
      await resumePythonRunAfterConnection(runId, connectionId);
      const generation = ++pythonPollGenerationRef.current;
      const planningDeadline = Date.now() + 90000;
      for (;;) {
        const run = await getPythonRunResilient(runId, generation);
        if (!run) return;
        const disposition = planningDisposition(run);
        if (disposition === "review") {
          pythonPlanRef.current = run.plan;
          setPlan(uiPlanFromRun(run));
          return;
        }
        if (disposition === "connection") {
          setPlan(uiConnectionPlanFromRun(run, interpretation));
          return;
        }
        if (disposition === "unavailable") {
          throw new Error(run.error || "AURA could not resume planning after the connection was verified.");
        }
        if (Date.now() >= planningDeadline) {
          throw new Error("Planning is taking longer than expected. Your saved task is safe to retry.");
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    } catch (error) {
      setPlan({
        interpretation,
        workflowName: "",
        estimatedTime: "",
        steps: [],
        error: error?.message || "AURA couldn't resume planning right now.",
      });
    } finally {
      setPlanLoading(false);
    }
  };

  const keepPlanInReview = useCallback((message) => {
    setPlan((previous) => ({
      ...(previous || { interpretation, steps: [] }),
      error: message || "This plan is not attached to a durable AURA run. Rebuild it before starting.",
    }));
    setPhase("plan");
  }, [interpretation]);

  // ---- Approve plan -> preview (both mock and custom) ----
  const handleApprove = useCallback((steps, name = "") => {
    approvedStepsRef.current = steps;
    setApprovedSteps(steps);
    setWorkflowName(name);
    if (editRunMode) {
      setEditFlag(detectNewConsequential(editOriginalStepsRef.current, steps));
      setEditReviewOpen(true);
      return;
    }
    if (!hasDurablePlan(pythonRunIdRef.current, pythonPlanRef.current)) {
      keepPlanInReview();
      return;
    }
    if (autoApprove) {
      startPythonExecution();
      return;
    }
    const requiresReview = steps.some((step) => step.riskLevel === "modify");
    if (!requiresReview) {
      startPythonExecution();
      return;
    }
    startPythonPreparation(steps);
  }, [editRunMode, autoApprove, keepPlanInReview]);

  const handlePreviewApprove = useCallback((editedSteps) => {
    if (editedSteps && editedSteps.length) {
      approvedStepsRef.current = editedSteps;
      setApprovedSteps(editedSteps);
    }
    if (!hasDurablePlan(pythonRunIdRef.current, pythonPlanRef.current)) {
      keepPlanInReview();
      return;
    }
    startPythonExecution(editedSteps, true);
  }, [keepPlanInReview]);

  const mapRuntimeSteps = (run) => {
    const runtimeSteps = (run.steps || []).map((step, index) => {
      const planned = approvedStepsRef.current[index];
      const preflightRetrying = index === 0
        && step.status === "pending"
        && run.automation_state?.status === "retrying";
      return {
        id: step.id,
        tool: planned?.tool || planToolName(step),
        action: planned?.title || planned?.action || friendlyStepTitle(step),
        riskLevel: step.consequential ? "modify" : "read",
        status: preflightRetrying ? "recovering" : step.status,
        started_at: step.started_at,
        completed_at: step.completed_at,
        liveOutput: preflightRetrying
          ? `→ ${run.automation_state.message || "AURA is retrying a temporary preflight failure automatically"}`
          : step.error
          ? `→ ${step.error}`
          : step.status === "completed"
            ? `→ ${planned?.output || "Completed successfully"}`
            : step.output?.provider_result
              ? "→ Provider response recorded; step not yet completed."
              : "",
        output: step.output,
      };
    });
    if (runtimeSteps.length || !run.automation_state) return runtimeSteps;
    const preflight = run.automation_state;
    return [{
      id: "aura-preflight",
      tool: "AURA preflight",
      action: "Verify connections and required resources",
      riskLevel: "read",
      status: preflight.status === "passed" ? "completed" : "recovering",
      liveOutput: preflight.message ? `→ ${preflight.message}` : "→ Checking access without changing external data",
    }];
  };

  const showRunRecovery = (run) => {
    setRecoveryRun(run);
    setRecoveryMessage("");
    setExecSteps(mapRuntimeSteps(run));
    setPhase("error");
  };

  const recoverRunStatus = async () => {
    try {
      const latest = await getPythonRun(pythonRunIdRef.current);
      if (needsRecovery(latest.status)) showRunRecovery(latest);
      else {
        // A failed request is not proof that execution failed. Offer a read-only check.
        setRecoveryRun(latest);
        setPhase("error");
      }
    } catch {
      setRecoveryRun((previous) => ({ ...previous, status: "unknown", steps: previous?.steps || [] }));
      setPhase("error");
    }
  };

  const handleRunRecovery = async (action = "retry") => {
    if (recoveryPendingRef.current) return;
    recoveryPendingRef.current = true;
    setRecoveryBusy(true);
    setRecoveryMessage("");
    try {
      const latest = await getPythonRun(pythonRunIdRef.current);
      const options = recoveryForRun(latest);
      if (needsRecovery(latest.status)) {
        if (action === "check") {
          showRunRecovery(latest);
          setRecoveryMessage("Status refreshed. Choose another safe approach or keep this workflow for later.");
          return;
        } else if (action === "connect" && options.canRetry) {
          const toolName = planToolName({ tool_slug: options.toolSlug || "", operation: "" });
          const connected = await connectTool(toolName, { connectionId: options.connectionId });
          const connectionId = connected.connection?.id || connected.tool?.id;
          if (options.blockerCode === "connection_required") {
            if (!connectionId) throw new Error(`${toolName} connected, but AURA could not identify the verified account.`);
            await resumePythonRunAfterConnection(latest.id, connectionId);
          } else {
            await resumePythonRun(latest.id);
          }
        } else if (action === "skip" && options.canSkip) {
          await resumePythonRun(latest.id, options.stepId, "skip");
        } else if (action === "retry" && options.canRetry) {
          await resumePythonRun(latest.id, options.stepId);
        } else {
          showRunRecovery(latest);
          setRecoveryMessage("This workflow still needs attention. Completed work is saved.");
          return;
        }
      }
      setRecoveryRun(null);
      let resumed = await getPythonRun(latest.id);
      if (!resumed.plan?.steps?.length) {
        setPlanLoading(true);
        setPhase("plan");
        const generation = ++pythonPollGenerationRef.current;
        for (;;) {
          resumed = await getPythonRunResilient(latest.id, generation);
          if (!resumed) return;
          if (resumed.plan?.steps?.length && resumed.status === "awaiting_approval") break;
          if (needsRecovery(resumed.status)) {
            setPlanLoading(false);
            showRunRecovery(resumed);
            return;
          }
          if (resumed.status === "cancelled") {
            forgetActivePythonRun(resumed.id);
            setPlanLoading(false);
            return;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
        pythonPlanRef.current = resumed.plan;
        const resumedPlan = uiPlanFromRun(resumed);
        setPlan(resumedPlan);
        setPlanLoading(false);
        approvedStepsRef.current = resumedPlan.steps;
        setApprovedSteps(resumedPlan.steps);
        setPhase("plan");
        return;
      }
      await startPythonExecution(null, false, true);
    } catch (error) {
      // Keep failures inline. Never claim a fix or duplicate a write to recover the UI.
      await recoverRunStatus();
      setRecoveryMessage(error.message || "AURA couldn't continue yet. The saved run is unchanged.");
    } finally {
      recoveryPendingRef.current = false;
      setRecoveryBusy(false);
    }
  };

  const keepRunForLater = () => reset();

  const cancelSavedRun = async (run = recoveryRun) => {
    if (!run || recoveryPendingRef.current) return;
    recoveryPendingRef.current = true;
    setRecoveryBusy(true);
    setRecoveryMessage("");
    try {
      await cancelPythonRun(run.id);
      forgetActivePythonRun(run.id);
      reset();
    } catch (error) {
      setRecoveryMessage(error.message || "AURA could not cancel this saved workflow yet.");
    } finally {
      recoveryPendingRef.current = false;
      setRecoveryBusy(false);
    }
  };

  const startPythonPreparation = async (reviewedUiSteps) => {
    const runId = pythonRunIdRef.current;
    if (!runId || !pythonPlanRef.current) return;
    const generation = ++pythonPollGenerationRef.current;
    setPhase("executing");
    setStartTime(Date.now());
    setCurrentStepIdx(0);
    setExecSteps(reviewedUiSteps.map((step) => ({
      tool: step.tool,
      action: step.title || step.action,
      riskLevel: step.riskLevel,
      status: "pending",
      liveOutput: "",
    })));
    try {
      // The reviewed UI is a presentation of this exact immutable backend plan.
      // Never send UI-only fields as executable steps.
      await approvePythonPlan(runId, pythonPlanRef.current.steps, false);
      for (;;) {
        const run = await getPythonRunResilient(runId, generation);
        if (!run) return;
        setExecSteps(mapRuntimeSteps(run));
        const active = (run.steps || []).findIndex((step) => step.status === "running");
        if (active >= 0) setCurrentStepIdx(active);
        if (run.status === "awaiting_approval") {
          const prepared = reviewedUiSteps.map((step, index) =>
            resolvedPreviewStep(step, run.steps?.[index])
          );
          approvedStepsRef.current = prepared;
          setApprovedSteps(prepared);
          setPhase("preview");
          return;
        }
        if (needsRecovery(run.status)) {
          showRunRecovery(run);
          return;
        }
        if (run.status === "cancelled") {
          forgetActivePythonRun(runId);
          finishExecution(null, run.error || "AURA couldn't complete this workflow after retrying safely.", "failed");
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 900));
      }
    } catch (error) {
      console.error("Python workflow preparation failed", error);
      await recoverRunStatus();
    }
  };

  const startPythonExecution = async (editedUiSteps = null, prepared = false, observeOnly = false) => {
    const runId = pythonRunIdRef.current;
    if (!runId || !pythonPlanRef.current) return;
    const generation = ++pythonPollGenerationRef.current;
    setPhase("executing");
    setStartTime(Date.now());
    const reviewedPlan = {
      ...pythonPlanRef.current,
      steps: pythonPlanRef.current.steps.map((step, index) => {
        const ui = editedUiSteps?.[index];
        if (!ui?.preview) return step;
        const patch = ui.preview.type === "email" ? { to: ui.preview.to, subject: ui.preview.subject, body: ui.preview.body } : {};
        return { ...step, arguments: { ...step.arguments, ...patch } };
      }),
    };
    try {
      if (observeOnly) {
        // Resume has already dispatched this run. Only observe; do not approve again.
      } else if (prepared) {
        const run = await getPythonRun(runId);
        const pending = (run.steps || []).filter((step) =>
          step.approval_status === "pending" && step.approval_preview?.status === "ready"
        );
        if (!pending.length) throw new Error("AURA is still preparing this approval.");
        for (const step of pending) {
          const uiStep = editedUiSteps?.[step.position] || approvedStepsRef.current[step.position];
          await decidePythonApproval(
            step.approval_id,
            true,
            editedArgumentsForStep(uiStep || {})
          );
        }
      } else {
        await approvePythonPlan(runId, reviewedPlan.steps, false);
      }
      for (;;) {
        const run = await getPythonRunResilient(runId, generation);
        if (!run) return;
        setExecSteps(mapRuntimeSteps(run));
        const active = (run.steps || []).findIndex((step) => step.status === "running");
        if (active >= 0) setCurrentStepIdx(active);
        if (run.status === "completed") {
          forgetActivePythonRun(runId);
          const outputs = run.result?.outputs || [];
          const synthesis = run.result?.unified_deliverable || {};
          const completedCount = run.result?.completed_steps ?? outputs.length;
          const resultLink = resultLinkFromOutputs(outputs);
          finishExecution({
            title: run.plan?.name || "Workflow completed",
            summary: synthesis.summary || "AURA completed the requested workflow.",
            metrics: [{ value: String(completedCount), label: completedCount === 1 ? "step completed" : "steps completed" }],
            outcomes: [{
              type: "document",
              title: "Result",
              detail: synthesis.deliverable || synthesis.summary || "The workflow completed successfully.",
              items: [{
                label: "Summary",
                detail: synthesis.deliverable || synthesis.summary || "The workflow completed successfully.",
              }],
              link: resultLink,
              linkLabel: resultLink ? "View result" : undefined,
            }],
            nextSteps: [],
          }, null, "completed");
          return;
        }
        if (run.status === "awaiting_approval") {
          const preparedSteps = approvedStepsRef.current.map((step, index) =>
            resolvedPreviewStep(step, run.steps?.[index])
          );
          approvedStepsRef.current = preparedSteps;
          setApprovedSteps(preparedSteps);
          setPhase("preview");
          return;
        }
        if (needsRecovery(run.status)) {
          showRunRecovery(run);
          return;
        }
        if (run.status === "cancelled") {
          forgetActivePythonRun(runId);
          finishExecution(null, run.error || "AURA couldn't complete this workflow after retrying safely.", "failed");
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 900));
      }
    } catch (error) {
      console.error("Python workflow execution failed", error);
      await recoverRunStatus();
    }
  };

  const runFrom = (startIdx) => {
    const template = execTemplateRef.current;
    const mock = pendingMock.current;
    const errIdx = mock?.errorStep?.index;
    const resolved = resolvedErrorRef.current;
    let lastDone = 0;

    for (let i = startIdx; i < template.length; i++) {
      const base = (i - startIdx) * STEP_DURATION * 1000;
      const isErr = errIdx != null && i === errIdx && !resolved;

      pushT(
        setTimeout(() => {
          setExecSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, status: "running" } : s)));
          setCurrentStepIdx(i);
        }, base)
      );

      if (isErr) {
        pushT(
          setTimeout(() => {
            setExecSteps((prev) => prev.map((s, idx) => (idx === i ? { ...s, status: "failed" } : s)));
            setPhase("error");
            notifyWorkflowError(mock?.results?.title || originalPromptRef.current, mock?.errorStep?.what);
            if (currentWorkflowIdRef.current) {
              aura.entities.Workflow.updateMany(
                { id: currentWorkflowIdRef.current },
                { $set: { last_run_status: "failed", last_run_date: new Date().toISOString() } }
              ).catch(() => {});
            }
          }, base + STEP_DURATION * 1000 * 0.7)
        );
        return; // error phase handles continuation
      }

      const doneAt = base + STEP_DURATION * 1000 * 0.8;
      lastDone = Math.max(lastDone, doneAt);
      pushT(
        setTimeout(() => {
          setExecSteps((prev) =>
            prev.map((s, idx) =>
              idx === i
                ? { ...s, status: "completed", liveOutput: template[i]._output, duration: template[i].duration }
                : s
            )
          );
        }, doneAt)
      );
    }

    pushT(setTimeout(() => finishExecution(), lastDone + 700));
  };

  const finishExecution = async (resultsFromBackend = null, errorMsg = null, executionStatus = "completed") => {
    const mock = pendingMock.current;
    let res;
    if (resultsFromBackend) {
      res = resultsFromBackend;
    } else if (mock && !errorMsg) {
      // Legacy recovery path only; normal and example executions use the backend.
      res = mock.results;
    } else if (errorMsg) {
      const needsAttention = executionStatus === "needs_attention";
      res = {
        title: needsAttention ? "Workflow needs attention" : "Workflow couldn't finish",
        summary: errorMsg,
        metrics: [],
        outcomes: [{
          type: "alert",
          title: needsAttention ? "AURA paused safely" : "AURA stopped safely",
          detail: errorMsg,
          attention: true,
        }],
        nextSteps: [],
      };
    } else {
      res = await aura.integrations.Core.InvokeLLM({
        prompt: `You are AURA. A workflow has just been executed successfully.

Confirmed intent: ${interpretation}
Steps completed: ${approvedStepsRef.current.map((s, i) => `${i + 1}. ${s.tool}: ${s.action}`).join("\n")}

Generate a results summary in plain, human-friendly language (not technical).
- title: short outcome title (4-6 words, no jargon)
- summary: one sentence describing what was accomplished, with specifics
- metrics: 3 realistic key numbers (value + label)
- outcomes: 3-5 "proof of work" lines, one per thing that happened. Each has: "type" (one of message/crm/email/document/metric/alert), "count" (the number of records, messages, tasks, etc. affected — omit if not countable), "title" (a SHORT label, e.g. "leads found", "emails sent", "tasks created"), "detail" (one line), "items" (the SPECIFIC records — each {label, detail}; aim 2-6), "link" (a realistic URL in the relevant tool, e.g. https://app.hubspot.com/contacts, https://mail.google.com/mail/u/0/#sent, https://acme.atlassian.net/jira/your-work, https://docs.google.com/spreadsheets/d/.../edit, https://acme.slack.com/archives/...), "linkLabel" (e.g. "Open in HubSpot", "Open in Gmail", "Open in Jira", "Open in Sheets", "View in Slack"). For anything that was skipped, flagged, or needs follow-up, set "attention": true and use linkLabel "View issue". Every concrete outcome should have a deep link.
- nextSteps: 3 short follow-up workflow suggestions`,
        response_json_schema: RESULTS_SCHEMA,
      });
    }
    res = {
      ...res,
      status: executionStatus === "completed" && !errorMsg ? "completed" : executionStatus,
    };
    setResults(res);
    setPhase("results");
    const stepCount = approvedStepsRef.current.length;
    const durationSec = startTime ? (Date.now() - startTime) / 1000 : 0;
    if (res.status === "completed") {
      notifyWorkflowComplete(res.title || originalPromptRef.current, durationSec, stepCount);
    } else {
      notifyWorkflowError(res.title || originalPromptRef.current);
    }

    if (currentRunIdRef.current && !resultsFromBackend) {
      try {
        await aura.entities.WorkflowRun.update(currentRunIdRef.current, {
          status: executionStatus === "failed" || errorMsg ? "failed" : "completed",
          title: workflowName || res.title,
          summary: res.summary,
          metrics: res.metrics,
          outcomes: res.outcomes,
          steps: approvedStepsRef.current,
          duration_seconds: startTime ? (Date.now() - startTime) / 1000 : null,
        });
      } catch (e) {
        /* ignore */
      }
    }
    if (currentWorkflowIdRef.current) {
      try {
        const wfSet = {
          last_run_status: executionStatus === "failed" || errorMsg ? "failed" : "completed",
          last_summary: res.summary,
          last_run_date: new Date().toISOString(),
          steps: approvedStepsRef.current,
        };
        if (workflowName) wfSet.name = workflowName;
        await aura.entities.Workflow.updateMany(
          { id: currentWorkflowIdRef.current },
          { $set: wfSet }
        );
      } catch (e) {
        /* ignore */
      }
    }
  };

  // ---- Error recovery ----
  const handleRetry = useCallback(() => {
    const mock = pendingMock.current;
    if (!mock) return;
    const errIdx = mock.errorStep.index;
    resolvedErrorRef.current = true;
    setExecSteps((prev) =>
      prev.map((s, idx) =>
        idx === errIdx
          ? { ...s, status: "completed", liveOutput: `→ Fix applied: ${mock.errorStep.fix}`, duration: s.duration || "1.0s" }
          : s
      )
    );
    setPhase("executing");
    runFrom(errIdx + 1);
  }, []);

  const handleSkip = useCallback(() => {
    const mock = pendingMock.current;
    if (!mock) return;
    const errIdx = mock.errorStep.index;
    resolvedErrorRef.current = true;
    setExecSteps((prev) =>
      prev.map((s, idx) => (idx === errIdx ? { ...s, status: "completed", liveOutput: "→ Skipped", duration: "0.2s" } : s))
    );
    setPhase("executing");
    runFrom(errIdx + 1);
  }, []);

  const handleEditFromError = useCallback(() => {
    clearTimeouts();
    setPhase("plan");
  }, []);

  // Run again / Edit & run from history: always run the CURRENT saved Workflow
  // definition — never the historical run's steps. Historical runs are immutable
  // records; re-running only ever creates a new run on the current workflow.
  const handleRerun = useCallback(
    (workflow, approval) => {
      if (!workflow) return;
      const auto = approval === "auto";
      const confirmedIntent = workflow.interpretation || workflow.prompt;
      reset();
      setAutoApprove(auto);
      currentWorkflowIdRef.current = workflow.id || null;
      setOriginalPrompt(workflow.prompt);
      originalPromptRef.current = workflow.prompt;
      setInterpretation(confirmedIntent);
      setWorkflowName(workflow.name || "");
      setPhase("plan");
      window.setTimeout(() => handleConfirm(confirmedIntent), 0);
    },
    [handleConfirm, reset]
  );

  // Start a fresh workflow from a natural-language prompt (Results "Run again" /
  // suggested next). Re-derives a new plan from the prompt.
  const handleStartFromPrompt = useCallback(
    (prompt) => {
      const keepWf = currentWorkflowIdRef.current;
      reset();
      currentWorkflowIdRef.current = keepWf || null;
      setTimeout(() => handleSubmit(prompt), 100);
    },
    [reset, handleSubmit]
  );

  const handleEditRun = (workflow, approval) => {
    if (!workflow) return;
    setEditRun({ ...workflow, title: workflow.name });
    setEditApproval(approval || "writes");
    setEditFlag(null);
    reset();
    setEditRunMode(true);
    currentWorkflowIdRef.current = workflow.id || null;
    setOriginalPrompt(workflow.prompt);
    originalPromptRef.current = workflow.prompt;
    setInterpretation(workflow.interpretation || workflow.prompt);
    editOriginalStepsRef.current = workflow.steps || [];
    setWorkflowName(workflow.name || "");
    setPlan({ steps: workflow.steps || [], interpretation: workflow.interpretation || workflow.prompt, workflowName: workflow.name || "", estimatedTime: "" });
    setPlanLoading(false);
    setPhase("plan");
  };

  const handleEditReviewRun = () => {
    setEditReviewOpen(false);
    setEditRunMode(false);
    handleConfirm(plan?.interpretation || interpretation);
  };

  useEffect(() => {
    // Seed the "Weekly creator approvals" example as a saved workflow so it
    // shows up in "My workflows" alongside anything the user actually runs.
    const PROMPT = WORKFLOW_EXAMPLES.find((e) => e.id === "creator-approvals")?.prompt;
    if (!PROMPT) return;
    (async () => {
      try {
        const existing = await aura.entities.Workflow.filter({ prompt: PROMPT }, "-created_date", 1);
        if (existing.length) return;
        const m = CREATOR_APPROVALS_MOCK;
        const now = new Date().toISOString();
        const wf = await aura.entities.Workflow.create({
          name: m.plan.workflowName || "Weekly creator approvals",
          prompt: PROMPT,
          interpretation: m.plan.interpretation,
          steps: m.plan.steps,
          last_run_status: "completed",
          last_run_date: now,
          last_summary: m.results.summary,
          run_count: 1,
        });
        await aura.entities.WorkflowRun.create({
          prompt: PROMPT,
          status: "completed",
          workflow_id: wf.id,
          title: m.plan.workflowName,
          summary: m.results.summary,
          metrics: m.results.metrics,
          outcomes: m.results.outcomes,
          steps: m.plan.steps,
          duration_seconds: 11,
        });
      } catch (e) {
        /* ignore */
      }
    })();
  }, []);

  useEffect(() => {
    hydrateConnections().catch(() => null);
    return () => {
      pythonPollGenerationRef.current += 1;
      clearTimeouts();
    };
  }, []);

  // Derive preview data + approval step (the modify step to call out)
  const mock = pendingMock.current;
  const previewData =
    mock?.preview || (approvedStepsRef.current.length ? { steps: approvedStepsRef.current } : null);
  let approvalStep = null;
  if (mock && mock.preview && mock.approvalIndex != null && plan) {
    const src = approvedSteps.length ? approvedSteps : plan.steps;
    const idx = mock.approvalIndex;
    approvalStep = {
      label: `${idx + 1}`,
      action: src[idx]?.action,
      riskNote: src[idx]?.riskNote,
    };
  } else if (!mock && approvedSteps.length) {
    const idx = approvedSteps.findIndex((s) => s.riskLevel === "modify");
    if (idx >= 0) {
      approvalStep = {
        label: `${idx + 1}`,
        action: approvedSteps[idx]?.action,
        riskNote: approvedSteps[idx]?.riskNote,
      };
    }
  }
  const activeRecovery = recoveryRun ? recoveryForRun(recoveryRun) : null;

  return (
    <div className="min-h-screen bg-background font-inter relative">
      <AmbientBackground phase={phase} />

      <div className="relative z-10 flex flex-col min-h-screen">
        <TopBar
          onHistoryOpen={() => setHistoryOpen(true)}
          onBack={phase === "input" ? null : handlePageBack}
        />

        <main className="flex-1 flex items-center justify-center px-4 py-8 md:py-12">
          <AnimatePresence mode="wait">
            {phase === "input" && (
              <motion.div key="input" exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.3 }} className="w-full">
                <CommandInput onSubmit={handleSubmit} examples={WORKFLOW_EXAMPLES} onPickExample={handlePickExample} />
              </motion.div>
            )}

            {phase === "confirm" && (
              <motion.div key="confirm" className="w-full flex justify-center">
                <ConfirmView
                  interpretation={interpretation}
                  originalPrompt={originalPrompt}
                  loading={interpretationLoading}
                  onConfirm={handleConfirm}
                  onEdit={reset}
                  onRegenerate={handleRegenerateInterpretation}
                />
              </motion.div>
            )}

            {phase === "plan" && (
              <motion.div
                key="plan"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4 }}
                className="w-full flex justify-center"
              >
                {planLoading ? (
                  <div className="flex flex-col items-center gap-4">
                    <ThinkingAnimation />
                    <p className="text-sm text-muted-foreground">AURA is building your plan…</p>
                  </div>
                ) : plan ? (
                  <PlanView
                    plan={plan}
                    hasPreview={!!mock?.preview}
                    onApprove={handleApprove}
                    onRevisePlan={handlePlanRevision}
                    onRetryPlan={handleRetryPlanning}
                    onConnectionRecovered={handlePlanningConnectionRecovered}
                    onBack={() => setPhase("confirm")}
                    approveLabel={editRunMode ? "Review changes" : "Start"}
                  />
                ) : null}
              </motion.div>
            )}

            {phase === "preview" && previewData && (
              <motion.div
                key="preview"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4 }}
                className="w-full flex justify-center"
              >
                <PreviewView preview={previewData} steps={approvedSteps} approvalStep={approvalStep} onApprove={handlePreviewApprove} onBack={() => setPhase("plan")} />
              </motion.div>
            )}

            {phase === "executing" && (
              <motion.div
                key="executing"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4 }}
                className="w-full flex justify-center"
              >
                <ExecutionView steps={execSteps} currentStepIndex={currentStepIdx} isReal={!mock} />
              </motion.div>
            )}

            {phase === "error" && (recoveryRun || mock?.errorStep) && (
              <motion.div
                key="error"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4 }}
                className="w-full flex justify-center"
              >
                <ErrorView
                  error={activeRecovery || mock.errorStep}
                  step={execSteps[recoveryRun ? activeRecovery.index : mock.errorStep.index]}
                  runSteps={execSteps}
                  busy={recoveryBusy}
                  message={recoveryMessage}
                  onRetry={recoveryRun
                    ? (activeRecovery.canRetry
                      ? () => handleRunRecovery(
                        ["connect_account", "reconnect_account"].includes(activeRecovery.blockerAction)
                          ? "connect"
                          : "retry"
                      )
                      : undefined)
                    : handleRetry}
                  onCheck={recoveryRun && !activeRecovery.canRetry ? () => handleRunRecovery("check") : undefined}
                  onAlternative={recoveryRun ? () => startAlternativePlan(recoveryRun) : undefined}
                  onSuggest={recoveryRun ? (suggestion) => startAlternativePlan(recoveryRun, suggestion) : undefined}
                  onLater={recoveryRun ? () => keepRunForLater(recoveryRun) : undefined}
                  onCancel={recoveryRun ? () => cancelSavedRun(recoveryRun) : undefined}
                  onEdit={recoveryRun ? undefined : handleEditFromError}
                  onSkip={recoveryRun ? (activeRecovery.canSkip ? () => handleRunRecovery("skip") : undefined) : handleSkip}
                />
              </motion.div>
            )}

            {phase === "results" && (
              <motion.div
                key="results"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className="w-full flex justify-center"
              >
                {results ? (
                  <ResultsView
                    results={results}
                    onNewWorkflow={reset}
                    onStartWorkflow={handleStartFromPrompt}
                    workflowPrompt={interpretation}
                    activity={execSteps}
                    prompt={originalPrompt}
                    interpretation={interpretation}
                  />
                ) : (
                  <div className="flex flex-col items-center gap-4">
                    <ThinkingAnimation />
                    <p className="text-sm text-muted-foreground">Compiling results…</p>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        <footer className="px-6 py-3 border-t border-white/5 flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground/40">AURA v2.6 · Durable autonomous runs</span>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-[11px] text-muted-foreground/40">System ready</span>
          </div>
        </footer>
      </div>

      <HistoryPanel open={historyOpen} onClose={() => setHistoryOpen(false)} onRerun={handleRerun} onEditRun={handleEditRun} />

      <EditRunReviewModal
        open={editReviewOpen}
        run={editRun}
        approval={editApproval}
        onApprovalChange={setEditApproval}
        flag={editFlag}
        onClose={() => setEditReviewOpen(false)}
        onRun={handleEditReviewRun}
      />
    </div>
  );
}

function ThinkingAnimation() {
  return (
    <div className="relative w-16 h-16">
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
        className="absolute inset-0 rounded-full border-2 border-transparent border-t-primary/60 border-r-accent/30"
      />
      <motion.div
        animate={{ rotate: -360 }}
        transition={{ duration: 5, repeat: Infinity, ease: "linear" }}
        className="absolute inset-2 rounded-full border-2 border-transparent border-b-accent/40 border-l-primary/20"
      />
      <div className="absolute inset-0 flex items-center justify-center">
        <motion.div
          animate={{ scale: [1, 1.2, 1] }}
          transition={{ duration: 1.5, repeat: Infinity }}
          className="w-3 h-3 rounded-full bg-gradient-to-br from-primary to-accent"
        />
      </div>
    </div>
  );
}
