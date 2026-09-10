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
import {
  approvePythonPlan,
  createPythonRun,
  decidePythonApproval,
  forgetActivePythonRun,
  getPythonRun,
  getResumablePythonRun,
  resumePythonRun,
  resumePythonRunAfterConnection,
} from "@/lib/auraApi";

const STEP_DURATION = 2.6;

const planToolName = (step) => {
  if (step.tool_slug === "google") {
    if (step.operation.startsWith("gmail.")) return "Gmail";
    if (step.operation.startsWith("calendar.")) return "Google Calendar";
    if (step.operation.startsWith("sheets.")) return "Google Sheets";
    return "Google Drive";
  }
  const names = {
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

const friendlyStepTitle = (step) => {
  const tool = planToolName(step);
  const reason = String(step.reason || "").toLowerCase();
  const operation = String(step.operation || "");

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

const pythonPlanForUi = (run) => ({
  workflowName: run.plan?.name,
  interpretation: run.plan?.interpretation,
  estimatedTime: run.plan?.planning_artifacts?.timings_ms?.total
    ? `Planned in ${(run.plan.planning_artifacts.timings_ms.total / 1000).toFixed(1)}s`
    : "Runs independently in the AURA control plane",
  steps: (run.plan?.steps || []).map((step) => ({
    tool: planToolName(step),
    title: friendlyStepTitle(step),
    iWill: cleanSentence(step.reason),
    action: cleanSentence(step.reason),
    detail: JSON.stringify(step.arguments, null, 2),
    reason: step.reason,
    output: step.expected_output,
    flow: [
      { label: "Uses", value: planToolName(step) },
      { label: "Creates", value: step.expected_output },
    ],
    riskLevel: step.consequential ? "modify" : "read",
    riskNote: step.consequential
      ? "AURA will pause immediately before this external submission and show the exact payload."
      : "",
  })),
});

const pythonExecutionSteps = (run) => {
  const firstPending = (run.steps || []).findIndex((step) => step.status === "pending");
  return (run.steps || []).map((step, index) => ({
    id: step.id,
    tool: planToolName(step),
    action: friendlyStepTitle(step),
    riskLevel: step.consequential ? "modify" : "read",
    status: run.automation_state?.status === "retrying" && index === firstPending
      ? "running"
      : step.status === "awaiting_approval" && run.plan_approved
      ? "pending"
      : step.status,
    liveOutput: step.output?.provider_result
      ? `→ Provider confirmed ${step.operation}`
      : step.error
      ? `→ ${step.error}`
      : run.automation_state?.status === "retrying" && step.status === "pending"
      ? `→ Preflight retry ${run.automation_state.attempt}; no action has been sent yet`
      : "",
    output: step.output,
  }));
};

const pythonResultForUi = (run) => {
  const outputs = run.result?.outputs || [];
  return {
    title: "Workflow completed by AURA agents",
    summary:
      run.result?.deliverable?.summary ||
      `${run.result?.completed_steps || outputs.length} provider actions completed with stored evidence.`,
    metrics: [
      {
        value: String(run.result?.completed_steps || outputs.length),
        label: "verified actions",
      },
    ],
    outcomes: outputs.map((output) => ({
      type: "document",
      title: output.operation,
      detail: `Confirmed by ${output.tool}`,
      items: [
        {
          label: "Provider evidence",
          detail: JSON.stringify(output.provider_result).slice(0, 500),
        },
      ],
    })),
    nextSteps: [],
  };
};

const pendingPythonApproval = (run) =>
  (run.steps || []).find(
    (step) =>
      step.status === "awaiting_approval" &&
      step.approval_status === "pending" &&
      step.approval_preview?.status === "ready"
  );

const approvalStepForUi = (step) => {
  const args = step.approval_preview?.arguments || {};
  let preview;
  if (step.operation === "gmail.send") {
    preview = {
      type: "email",
      to: args.to || "",
      subject: args.subject || "",
      body: args.body || "",
      note: "This exact email will be sent only after you approve it.",
    };
  } else if (step.operation === "sheets.append") {
    const rows = Array.isArray(args.values) ? args.values : [];
    const width = Math.max(1, ...rows.map((row) => (Array.isArray(row) ? row.length : 1)));
    preview = {
      type: "table",
      title: `${args.range || "Spreadsheet"} · ${rows.length} row${rows.length === 1 ? "" : "s"}`,
      columns: Array.from({ length: width }, (_, index) => `Column ${index + 1}`),
      rows: rows.map((row) => (Array.isArray(row) ? row : [row])),
      previewNote: "Only these rows will be appended after approval.",
    };
  } else {
    const records = Array.isArray(args.records) ? args.records : null;
    preview = {
      type: "list",
      title: records
        ? `${records.length} record${records.length === 1 ? "" : "s"} ready to submit`
        : step.operation,
      items: records
        ? records.map((record, index) => ({
            label: record.handle || record.creatorUsername || record.name || `Record ${index + 1}`,
            detail: JSON.stringify(record).slice(0, 500),
          }))
        : Object.entries(args).map(([label, value]) => ({
            label,
            detail: JSON.stringify(value).slice(0, 500),
          })),
    };
  }
  return {
    tool: planToolName(step),
    action: friendlyStepTitle(step),
    detail: JSON.stringify(args, null, 2),
    output: "A provider-confirmed receipt",
    flow: [{ label: "Uses", value: planToolName(step) }],
    riskLevel: "modify",
    riskNote: "Review this exact payload. Approval triggers the external action immediately.",
    preview,
    _approvalId: step.approval_id,
    _approvalArguments: args,
  };
};

const editedApprovalArguments = (step) => {
  const original = step?._approvalArguments || {};
  if (step?.preview?.type !== "email") return original;
  return {
    ...original,
    to: step.preview.to,
    subject: step.preview.subject,
    body: step.preview.body,
  };
};

const blockerForUi = (run) => {
  const failedStep = (run.steps || []).find((step) => step.status === "failed");
  const blocker = {
    ...(run.blocker || {}),
    step_id: run.blocker?.step_id || failedStep?.id || null,
  };
  const fixes = {
    reconnect_account: blocker.connected_account
      ? `Reconnect ${planToolName({ tool_slug: blocker.tool_slug, operation: "" })} with an account that can access ${blocker.resource_name || "the required resource"}. Currently selected: ${blocker.connected_account}.`
      : `Reconnect ${planToolName({ tool_slug: blocker.tool_slug, operation: "" })} and grant the required access.`,
    connect_account: `Connect ${planToolName({ tool_slug: blocker.tool_slug, operation: "" })}; AURA will then resume this saved run.`,
    choose_resource: `Choose one exact resource for ${blocker.resource_name || "this step"}; AURA will never guess.`,
    inspect_run: "Open the saved run details. Completed work and provider receipts are preserved.",
  };
  return {
    what: blocker.message || run.error || "AURA preserved the run but could not continue safely.",
    why: blocker.code ? `Exact blocker: ${blocker.code}` : "The backend reported a non-retryable blocker.",
    fixShort: fixes[blocker.action] || "Retry the saved run after the blocker is resolved.",
    buttonLabel:
      blocker.action === "reconnect_account" || blocker.action === "connect_account"
        ? "Connect & resume"
        : "Retry saved run",
    canRetry: blocker.action !== "choose_resource",
    blocker,
  };
};

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
  const [runError, setRunError] = useState(null);
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
  const pendingPythonApprovalRef = useRef(null);
  const pythonPollGenerationRef = useRef(0);
  const runRequestKeyRef = useRef(null);

  const clearTimeouts = () => {
    timeoutRefs.current.forEach(clearTimeout);
    timeoutRefs.current = [];
  };
  const pushT = (t) => timeoutRefs.current.push(t);

  const reset = useCallback(() => {
    clearTimeouts();
    pendingMock.current = null;
    resolvedErrorRef.current = false;
    approvedStepsRef.current = [];
    setApprovedSteps([]);
    execTemplateRef.current = [];
    currentRunIdRef.current = null;
    currentWorkflowIdRef.current = null;
    pythonRunIdRef.current = null;
    pythonPlanRef.current = null;
    pendingPythonApprovalRef.current = null;
    pythonPollGenerationRef.current += 1;
    runRequestKeyRef.current = null;
    setPhase("input");
    setOriginalPrompt("");
    setInterpretation("");
    setPlan(null);
    setResults(null);
    setRunError(null);
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
    (editedInterpretation) => {
      setInterpretation(editedInterpretation);
      {
        setPlanLoading(true);
        setPhase("plan");
        (async () => {
          try {
            const planningPrompt = editedInterpretation.trim() || originalPromptRef.current;
            runRequestKeyRef.current ||=
              globalThis.crypto?.randomUUID?.() ||
              `run-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const created = await createPythonRun(
              planningPrompt,
              null,
              runRequestKeyRef.current
            );
            pythonRunIdRef.current = created.id;
            let run;
            for (let attempt = 0; attempt < 120; attempt += 1) {
              run = await getPythonRun(created.id);
              if (run.status === "awaiting_approval" && run.plan?.steps?.length) break;
              if (["failed", "blocked", "waiting_for_action", "cancelled"].includes(run.status)) {
                throw new Error(run.blocker?.message || run.error || `Workflow ${run.status}`);
              }
              await new Promise((resolve) => setTimeout(resolve, 1000));
            }
            if (!run?.plan?.steps?.length) throw new Error("Python orchestrator did not return a plan in time");
            pythonPlanRef.current = run.plan;
            setPlan(pythonPlanForUi(run));
          } catch (error) {
            setPlan({
              interpretation: editedInterpretation,
              workflowName: originalPromptRef.current.slice(0, 60),
              steps: [],
              error: error.message || "AURA could not build this plan. Please try again.",
            });
            setResults({ title: "Orchestrator unavailable", summary: error.message, metrics: [], outcomes: [], nextSteps: [] });
          } finally { setPlanLoading(false); }
        })();
        return;
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
    if (autoApprove) {
      if (pythonRunIdRef.current) startPythonExecution();
      else startExecution();
      return;
    }
    setPhase("preview");
  }, [editRunMode, autoApprove]);

  const handlePreviewApprove = useCallback((editedSteps) => {
    if (editedSteps && editedSteps.length) {
      approvedStepsRef.current = editedSteps;
      setApprovedSteps(editedSteps);
    }
    if (pendingPythonApprovalRef.current && editedSteps?.[0]) {
      const pending = pendingPythonApprovalRef.current;
      pendingPythonApprovalRef.current = null;
      setPhase("executing");
      setStartTime((value) => value || Date.now());
      decidePythonApproval(
        pending.approval_id,
        true,
        editedApprovalArguments(editedSteps[0])
      )
        .then(() => monitorPythonRun(pythonRunIdRef.current))
        .catch((error) => {
          setRunError({
            what: error.message,
            why: "The reviewed external action was not accepted by the control plane.",
            fixShort: "Review the exact payload and try again. Nothing was submitted.",
            buttonLabel: "Review again",
            canRetry: true,
          });
          pendingPythonApprovalRef.current = pending;
          setPhase("error");
        });
    } else if (pythonRunIdRef.current) startPythonExecution(editedSteps);
    else startExecution();
  }, []);

  const monitorPythonRun = async (runId) => {
    if (!runId) return;
    pythonRunIdRef.current = runId;
    const generation = ++pythonPollGenerationRef.current;
    setPhase("executing");
    setStartTime((value) => value || Date.now());
    let consecutivePollErrors = 0;
    for (;;) {
      if (pythonPollGenerationRef.current !== generation) return;
      let run;
      try {
        run = await getPythonRun(runId);
        consecutivePollErrors = 0;
      } catch (error) {
        // Browser/network interruptions do not change the backend run. Keep
        // polling while the durable worker continues. Back off locally so an
        // outage cannot create a request storm.
        if (!error.status || error.status === 429 || error.status >= 500) {
          consecutivePollErrors += 1;
          const delay = Math.min(15000, 1000 * 2 ** Math.min(consecutivePollErrors, 4));
          await new Promise((resolve) => setTimeout(resolve, delay));
          continue;
        }
        throw error;
      }
      if (["queued", "planning"].includes(run.status) && !run.plan?.steps?.length) {
        setPhase("plan");
        setPlanLoading(true);
        await new Promise((resolve) => setTimeout(resolve, 900));
        continue;
      }
      setExecSteps(pythonExecutionSteps(run));
      const active = (run.steps || []).findIndex((step) => step.status === "running");
      const firstIncomplete = (run.steps || []).findIndex(
        (step) => !["completed", "skipped"].includes(step.status)
      );
      if (active >= 0) setCurrentStepIdx(active);
      else if (firstIncomplete >= 0) setCurrentStepIdx(firstIncomplete);

      if (run.status === "completed") {
        forgetActivePythonRun(runId);
        finishExecution(pythonResultForUi(run), null, "completed");
        return;
      }
      if (run.status === "awaiting_approval" && run.plan_approved) {
        const pending = pendingPythonApproval(run);
        if (pending) {
          pendingPythonApprovalRef.current = pending;
          const uiStep = approvalStepForUi(pending);
          approvedStepsRef.current = [uiStep];
          setApprovedSteps([uiStep]);
          setPhase("preview");
          return;
        }
      }
      if (run.status === "awaiting_approval" && !run.plan_approved) {
        pythonPlanRef.current = run.plan;
        setOriginalPrompt(run.prompt);
        originalPromptRef.current = run.prompt;
        setInterpretation(run.plan?.interpretation || run.prompt);
        setPlan(pythonPlanForUi(run));
        setPlanLoading(false);
        setPhase("plan");
        return;
      }
      if (["failed", "blocked", "waiting_for_action", "cancelled"].includes(run.status)) {
        if (run.status === "cancelled") forgetActivePythonRun(runId);
        setRunError(blockerForUi(run));
        setPhase("error");
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
  };

  const startPythonExecution = async (editedUiSteps = null) => {
    const runId = pythonRunIdRef.current;
    if (!runId || !pythonPlanRef.current) return;
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
      await approvePythonPlan(runId, reviewedPlan.steps);
      await monitorPythonRun(runId);
    } catch (error) {
      setRunError({
        what: error.message,
        why: "The control plane could not start the reviewed plan.",
        fixShort: "AURA kept the plan unchanged. Retry when the connection is available.",
        buttonLabel: "Retry saved run",
        canRetry: true,
      });
      setPhase("error");
    }
  };

  // ---- Execution ----
  const startExecution = async () => {
    clearTimeouts();
    setPhase("executing");
    setCurrentStepIdx(0);
    setStartTime(Date.now());

    // Examples may supply a pre-built plan, but execution is never mocked.
    // Every approved plan goes through the same backend provider executor.
    const template = approvedStepsRef.current.map((s) => ({
      tool: s.tool,
      action: s.action || s.iWill || "",
      riskLevel: s.riskLevel,
      status: "pending",
      output: "",
    }));
    execTemplateRef.current = template;
    setExecSteps(template);

    try {
      let wfId = currentWorkflowIdRef.current;
      const baseName = workflowName || plan?.workflowName || originalPromptRef.current.slice(0, 60);
      const now = new Date().toISOString();
      const startUpdate = (id) =>
        aura.entities.Workflow.updateMany(
          { id },
          { $set: { steps: approvedStepsRef.current, interpretation: plan?.interpretation || interpretation, last_run_status: "running", last_run_date: now }, $inc: { run_count: 1 } }
        );
      if (!wfId) {
        // Reuse an existing saved workflow for the same prompt, else create one
        const existing = await aura.entities.Workflow.filter({ prompt: originalPromptRef.current }, "-created_date", 1).catch(() => []);
        if (existing.length) {
          wfId = existing[0].id;
          currentWorkflowIdRef.current = wfId;
          await startUpdate(wfId);
        } else {
          const wf = await aura.entities.Workflow.create({
            name: baseName,
            prompt: originalPromptRef.current,
            interpretation: plan?.interpretation || interpretation,
            steps: approvedStepsRef.current,
            last_run_status: "running",
            last_run_date: now,
            run_count: 1,
          });
          wfId = wf.id;
          currentWorkflowIdRef.current = wfId;
        }
      } else {
        await startUpdate(wfId);
      }
      const run = await aura.entities.WorkflowRun.create({ prompt: originalPromptRef.current, status: "running", workflow_id: wfId });
      currentRunIdRef.current = run.id;
    } catch (e) {
      /* ignore */
    }

    if (!currentRunIdRef.current) {
      finishExecution(null, "AURA could not create a persistent workflow run. No external actions were attempted.", "failed");
      return;
    }
    runRealWorkflow(currentRunIdRef.current);
  };

  const runRealWorkflow = async (runId) => {
    if (!runId) return;
    let stopped = false;
    const poll = async () => {
      while (!stopped) {
        try {
          const run = await aura.entities.WorkflowRun.get(runId);
          if (run.steps && run.steps.length) {
            setExecSteps(run.steps.map((s) => ({ ...s, liveOutput: s.output || "" })));
            const idx = run.steps.findIndex((s) => s.status === "running");
            setCurrentStepIdx(idx >= 0 ? idx : Math.max(0, run.steps.filter((s) => s.status === "completed").length - 1));
          }
        } catch { /* ignore */ }
        await new Promise((r) => setTimeout(r, 900));
      }
    };
    poll();

    try {
      const res = await aura.functions.invoke("orchestrateWorkflow", {
        runId,
        steps: approvedStepsRef.current,
        interpretation: plan?.interpretation || interpretation,
        prompt: originalPromptRef.current,
      });
      stopped = true;
      const data = res.data || {};
      if (data.error) throw new Error(data.error);
      if (data.steps) setExecSteps(data.steps.map((s) => ({ ...s, liveOutput: s.output || "" })));
      finishExecution(data.results, null, data.status || "completed");
    } catch (e) {
      stopped = true;
      finishExecution(null, e.message);
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
      res = {
        title: "Workflow failed",
        summary: errorMsg,
        metrics: [],
        outcomes: [{ type: "alert", title: "Execution error", detail: errorMsg, attention: true }],
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
    setResults(res);
    setPhase("results");
    const stepCount = approvedStepsRef.current.length;
    const durationSec = startTime ? (Date.now() - startTime) / 1000 : 0;
    notifyWorkflowComplete(res.title || originalPromptRef.current, durationSec, stepCount);

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

  const handlePythonRecovery = useCallback(async () => {
    if (pendingPythonApprovalRef.current) {
      const uiStep = approvalStepForUi(pendingPythonApprovalRef.current);
      approvedStepsRef.current = [uiStep];
      setApprovedSteps([uiStep]);
      setPhase("preview");
      return;
    }
    const runId = pythonRunIdRef.current;
    if (!runId) return;
    const blocker = runError?.blocker || {};
    setPhase("executing");
    setRunError(null);
    try {
      if (["connect_account", "reconnect_account"].includes(blocker.action)) {
        const toolName = blocker.tool_slug === "google"
          ? "Google Sheets"
          : planToolName({ tool_slug: blocker.tool_slug, operation: "" });
        const connection = await connectTool(toolName);
        if (blocker.code === "connection_required" && connection.connection?.id) {
          await resumePythonRunAfterConnection(runId, connection.connection.id);
        } else {
          await resumePythonRun(runId, "retry", blocker.step_id || null);
        }
      } else {
        await resumePythonRun(runId, "retry", blocker.step_id || null);
      }
      await monitorPythonRun(runId);
    } catch (error) {
      setRunError({
        what: error.message,
        why: "AURA could not clear the exact blocker yet; the saved run is unchanged.",
        fixShort: "Complete the requested account or resource action, then retry this saved run.",
        buttonLabel: "Try again",
        canRetry: true,
        blocker,
      });
      setPhase("error");
    }
  }, [runError]);

  // Run again / Edit & run from history: always run the CURRENT saved Workflow
  // definition — never the historical run's steps. Historical runs are immutable
  // records; re-running only ever creates a new run on the current workflow.
  const handleRerun = useCallback(
    (workflow, approval) => {
      if (!workflow) return;
      const auto = approval === "auto";
      reset();
      setAutoApprove(auto);
      currentWorkflowIdRef.current = workflow.id || null;
      setOriginalPrompt(workflow.prompt);
      originalPromptRef.current = workflow.prompt;
      setInterpretation(workflow.interpretation || workflow.prompt);
      setWorkflowName(workflow.name || "");
      setPlan({ steps: workflow.steps || [], interpretation: workflow.interpretation || workflow.prompt, workflowName: workflow.name || "", estimatedTime: "" });
      setPlanLoading(false);
      setPhase("plan");
    },
    [reset]
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
    let cancelled = false;
    (async () => {
      try {
        await hydrateConnections();
        const run = await getResumablePythonRun();
        if (!run || cancelled) return;
        pythonRunIdRef.current = run.id;
        pythonPlanRef.current = run.plan;
        setOriginalPrompt(run.prompt);
        originalPromptRef.current = run.prompt;
        setInterpretation(run.plan?.interpretation || run.prompt);
        if (run.status === "awaiting_approval" && !run.plan_approved) {
          setPlan(pythonPlanForUi(run));
          setPlanLoading(false);
          setPhase("plan");
          return;
        }
        await monitorPythonRun(run.id);
      } catch (error) {
        if (cancelled) return;
        setRunError({
          what: error.message,
          why: "The browser could not restore the latest saved backend run.",
          fixShort: "Reload to try restoration again. The backend run was not cancelled.",
          buttonLabel: "Restore saved run",
          canRetry: true,
        });
        setPhase("error");
      }
    })();
    return () => {
      cancelled = true;
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
                <PreviewView
                  preview={previewData}
                  steps={approvedSteps}
                  approvalStep={approvalStep}
                  onApprove={handlePreviewApprove}
                  onBack={() => setPhase(pendingPythonApprovalRef.current ? "executing" : "plan")}
                  actionTime={!!pendingPythonApprovalRef.current}
                />
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

            {phase === "error" && (mock?.errorStep || runError) && (
              <motion.div
                key="error"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4 }}
                className="w-full flex justify-center"
              >
                <ErrorView
                  error={mock?.errorStep || runError}
                  step={
                    mock?.errorStep
                      ? execSteps[mock.errorStep.index]
                      : execSteps.find((step) => step.id === runError?.blocker?.step_id)
                  }
                  runSteps={execSteps}
                  onRetry={mock?.errorStep ? handleRetry : handlePythonRecovery}
                  onEdit={mock?.errorStep ? handleEditFromError : null}
                  onSkip={mock?.errorStep ? handleSkip : null}
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
          <span className="text-[11px] text-muted-foreground/40">AURA v2.6 · Durable autonomous execution</span>
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
