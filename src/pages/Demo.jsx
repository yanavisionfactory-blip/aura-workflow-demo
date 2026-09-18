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
import { connectTool } from "@/lib/connectService";
import { getAllConnections } from "@/lib/connectionsStore";
import { CATALOG, catalogEntryFor } from "@/lib/toolCatalog";
import { announceWorkflowHistoryChanged } from "@/lib/workflowHistory.mjs";
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
  recoveryProgressMessage,
  recoveryForRun,
  visibleRecoveryStepStatus,
} from "@/lib/runRecovery.mjs";
import {
  approvalStartFailure,
  planningConnectionRequirements,
  planningDisposition,
  promptConnectionRequirements,
  shouldStartFreshPlanningRun,
} from "@/lib/planningFlow.mjs";
import { hasDurablePlan, planningRequestPrompt } from "@/lib/runtimePlan.mjs";
import { weatherStepTitle } from "@/lib/planPresentation.mjs";
import { instantLanguagePlan, languageDraftPrompt } from "@/lib/languagePlan.mjs";
import { primaryResultFromOutputs } from "@/lib/resultPresentation.mjs";
import {
  editedArgumentsForStep,
  resolvedApprovalStep,
} from "@/lib/approvalReview.mjs";

const STEP_DURATION = 2.6;
const PLANNING_WAIT_TIMEOUT_MS = 30_000;
const PLANNING_POLL_INTERVAL_MS = 750;
const PLANNING_TRANSIENT_FAILURE_LIMIT = 3;

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
  return catalogEntryFor(step.tool_slug)?.name || names[step.tool_slug] || step.tool_slug;
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
    .replace(/^i\s+will\s+/i, "")
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

  if (operation === "weather.forecast") return weatherStepTitle(step);
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
    riskNote: step.consequential
      ? "This external action is included in the plan you approve with Start."
      : "",
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
  ...uiPlanFromRun(run),
  workflowName: run.plan?.name || "",
  interpretation: run.plan?.interpretation || interpretation || run.prompt,
  estimatedTime: run.plan?.steps?.length
    ? "Plan ready — connect the required accounts to enable execution"
    : "Planning resumes after the connection is verified",
  connectionRequirements: planningConnectionRequirements(run),
  connectionChecklist: Array.isArray(run.connection_requirements)
    ? run.connection_requirements
    : [],
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
  const [previewError, setPreviewError] = useState("");
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
  const languageDraftGenerationRef = useRef(0);
  const handleConfirmRef = useRef(null);
  const startPythonExecutionRef = useRef(null);
  const queuedPlanStartRef = useRef(null);
  const runRequestKeyRef = useRef(null);
  const lastPlanningIntentRef = useRef("");
  const historySavePromiseRef = useRef(null);

  const clearTimeouts = () => {
    timeoutRefs.current.forEach(clearTimeout);
    timeoutRefs.current = [];
  };
  const pushT = (t) => timeoutRefs.current.push(t);

  const getPythonRunResilient = async (runId, generation, maxTransientFailures = Number.POSITIVE_INFINITY) => {
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

  const createPythonRunResilient = async (
    prompt,
    workflowId,
    requestKey,
    inputs,
    maxTransientFailures = PLANNING_TRANSIENT_FAILURE_LIMIT,
  ) => {
    let transientFailures = 0;
    for (;;) {
      try {
        return await createPythonRun(prompt, workflowId, requestKey, inputs);
      } catch (error) {
        const transient = !error.status || error.status === 429 || error.status >= 500;
        if (!transient) throw error;
        transientFailures += 1;
        if (transientFailures >= maxTransientFailures) throw error;
        const delay = Math.min(15000, 1000 * (2 ** Math.min(transientFailures - 1, 4)));
        await new Promise((resolve) => window.setTimeout(resolve, delay));
      }
    }
  };

  const reset = useCallback(() => {
    clearTimeouts();
    pythonPollGenerationRef.current += 1;
    languageDraftGenerationRef.current += 1;
    runRequestKeyRef.current = null;
    lastPlanningIntentRef.current = "";
    historySavePromiseRef.current = null;
    queuedPlanStartRef.current = null;
    pendingMock.current = null;
    resolvedErrorRef.current = false;
    approvedStepsRef.current = [];
    setApprovedSteps([]);
    setPreviewError("");
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
    else if (phase === "executing" || phase === "error") {
      queuedPlanStartRef.current = null;
      setPhase("plan");
    }
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
      setPlan(mock.plan);
      setPlanLoading(false);
      setPhase("plan");
      return;
    }

    // The first submit must always produce a readable language plan. Intent
    // review remains available from Back, but it never gates plan display.
    setInterpretation(prompt);
    setInterpretationLoading(false);
    handleConfirmRef.current?.(prompt);
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
        const confirmedIntent = editedInterpretation.trim() || originalPromptRef.current;
        const explicitRequirements = promptConnectionRequirements(
          confirmedIntent,
          CATALOG.map((tool) => ({ ...tool, slug: tool.provider })),
          getAllConnections(),
        );
        const immediatePlan = {
          ...instantLanguagePlan(confirmedIntent, CATALOG, userSelectedToolsRef.current),
          connectionRequirements: explicitRequirements,
        };
        const languageDraftGeneration = ++languageDraftGenerationRef.current;

        // The readable plan is independent from connector readiness. Show a
        // useful language draft now; refine and compile it in parallel.
        setPlan(immediatePlan);
        setPlanLoading(false);
        setPhase("plan");

        aura.integrations.Core
          .InvokeLLM({
            prompt: languageDraftPrompt(confirmedIntent, userSelectedToolsRef.current),
            response_json_schema: PLAN_SCHEMA,
          })
          .then((draft) => {
            if (
              languageDraftGenerationRef.current !== languageDraftGeneration
              || !Array.isArray(draft?.steps)
              || draft.steps.length === 0
            ) return;
            setPlan((current) => current?.provisional ? {
              ...draft,
              steps: draft.steps.map((step) => ({
                ...step,
                iWill: firstPersonStepCopy(step.iWill || step.reason),
              })),
              interpretation: draft.interpretation || confirmedIntent,
              estimatedTime: "Plan ready — validating executable details backstage",
              connectionRequirements: current.connectionRequirements || explicitRequirements,
              provisional: true,
              compileState: current.compileState || "validating",
              compileError: current.compileError,
            } : current);
          })
          .catch(() => {
            // The immediate language draft is already visible. Exact execution
            // compilation remains authoritative and continues independently.
          });

        return (async () => {
          try {
            const previousRunId = pythonRunIdRef.current;
            const startFresh = shouldStartFreshPlanningRun({
              nextIntent: confirmedIntent,
              activeIntent: lastPlanningIntentRef.current,
              hasActiveRequest: Boolean(previousRunId || runRequestKeyRef.current),
              revisionInstruction,
            });
            if (startFresh) {
              pythonPollGenerationRef.current += 1;
              runRequestKeyRef.current = null;
              pythonRunIdRef.current = null;
              pythonPlanRef.current = null;
              if (previousRunId) {
                await cancelPythonRun(previousRunId).catch(() => {});
                forgetActivePythonRun(previousRunId);
              }
            }
            lastPlanningIntentRef.current = confirmedIntent;
            const planningPrompt = planningRequestPrompt(confirmedIntent, revisionInstruction);
            const planningDeadline = Date.now() + PLANNING_WAIT_TIMEOUT_MS;
            runRequestKeyRef.current ||= globalThis.crypto?.randomUUID?.()
              || `aura-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const resources = attachedResourcesRef.current || {};
            const created = await createPythonRunResilient(planningPrompt, null, runRequestKeyRef.current, {
              requested_tools: userSelectedToolsRef.current,
              saved_workflow_id: currentWorkflowIdRef.current,
              attached_documents: (resources.documents || []).map(({ name, file_url, size }) => ({
                name,
                file_url,
                size,
              })),
            });
            pythonRunIdRef.current = created.id;
            const generation = ++pythonPollGenerationRef.current;
            let run;
            for (;;) {
              if (Date.now() >= planningDeadline) {
                throw new Error("AURA couldn't prepare this workflow within 30 seconds.");
              }
              run = await getPythonRunResilient(
                created.id,
                generation,
                PLANNING_TRANSIENT_FAILURE_LIMIT,
              );
              if (!run) return;
              const disposition = planningDisposition(run);
              if (disposition === "review") break;
              if (disposition === "connection") {
                queuedPlanStartRef.current = null;
                setPhase("plan");
                pythonPlanRef.current = run.plan || null;
                const connectionPlan = uiConnectionPlanFromRun(run, editedInterpretation);
                setPlan((current) => connectionPlan.steps.length ? {
                  ...connectionPlan,
                  provisional: false,
                  compileState: "waiting_for_connection",
                } : {
                  ...(current || immediatePlan),
                  ...connectionPlan,
                  workflowName: connectionPlan.workflowName || current?.workflowName || immediatePlan.workflowName,
                  steps: current?.steps?.length ? current.steps : immediatePlan.steps,
                  provisional: true,
                  compileState: "waiting_for_connection",
                });
                return;
              }
              if (disposition === "unavailable") throw new Error(
                run.error || "The execution backend needs more setup before it can build this plan."
              );
              await new Promise((resolve) => setTimeout(resolve, PLANNING_POLL_INTERVAL_MS));
            }
            pythonPlanRef.current = run.plan;
            const compiledPlan = {
              ...uiPlanFromRun(run),
              provisional: false,
              compileState: "ready",
            };
            setPlan(compiledPlan);
            const queuedStart = queuedPlanStartRef.current;
            if (queuedStart) {
              queuedPlanStartRef.current = null;
              approvedStepsRef.current = compiledPlan.steps;
              setApprovedSteps(compiledPlan.steps);
              setWorkflowName(queuedStart.name || compiledPlan.workflowName || "");
              startPythonExecutionRef.current?.();
            }
          } catch (error) {
            console.warn("Executable planning unavailable; the language plan remains visible", error);
            const queuedStart = queuedPlanStartRef.current;
            queuedPlanStartRef.current = null;
            if (queuedStart) setPhase("plan");
            if (pythonRunIdRef.current) forgetActivePythonRun(pythonRunIdRef.current);
            pythonRunIdRef.current = null;
            pythonPlanRef.current = null;
            runRequestKeyRef.current = null;
            setPlan((current) => ({
              ...(current || immediatePlan),
              estimatedTime: "Plan ready — preparation timed out",
              connectionRequirements: explicitRequirements,
              provisional: true,
              compileState: "blocked",
              compileError: error?.message || "AURA couldn't prepare this workflow quickly enough.",
            }));
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
- The exact verified connector names available now are: ${CATALOG.map((tool) => tool.name).join(", ")}.
- Use only those exact names for external-tool steps. AURA Intelligence may be used only for reasoning over attached documents or data already produced by a verified connector.
- Prefer an already-connected tool when it has the required capability.
- If no released connector can perform a required step, do not invent a provider or ask for API keys, MCP endpoints, OAuth client details, or custom configuration. State the unavailable capability clearly in "riskNote" so AURA can preserve the plan until Connector Engineer releases a safe provider.

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
- Be honest about quality and capability gaps. Never present LLM-generated guesses as verified provider data.
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

  // handleSubmit is declared earlier for the existing recovery callbacks; the
  // ref lets the first user action enter this planner without a second click.
  handleConfirmRef.current = handleConfirm;

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

  const handlePlanningConnectionRecovered = async (recoveries) => {
    const runId = pythonRunIdRef.current;
    const connections = Array.isArray(recoveries) ? recoveries : [];
    const connectionIds = [...new Set(connections.map((item) => item?.connectionId).filter(Boolean))];
    if (!runId || connectionIds.length === 0) return handleRetryPlanning();
    setPlan((current) => current ? {
      ...current,
      provisional: true,
      compileState: "validating",
      compileError: "",
    } : current);
    try {
      for (const connectionId of connectionIds) {
        const latest = await getPythonRun(runId);
        if (!["waiting_for_action"].includes(latest.status)) break;
        await resumePythonRunAfterConnection(runId, connectionId);
      }
      const generation = ++pythonPollGenerationRef.current;
      for (;;) {
        const run = await getPythonRunResilient(runId, generation);
        if (!run) return;
        const disposition = planningDisposition(run);
        if (disposition === "review") {
          pythonPlanRef.current = run.plan;
          setPlan({ ...uiPlanFromRun(run), provisional: false, compileState: "ready" });
          return;
        }
        if (disposition === "connection") {
          pythonPlanRef.current = run.plan || null;
          const connectionPlan = uiConnectionPlanFromRun(run, interpretation);
          setPlan((current) => connectionPlan.steps.length ? {
            ...connectionPlan,
            provisional: false,
            compileState: "waiting_for_connection",
          } : {
            ...(current || connectionPlan),
            ...connectionPlan,
            steps: current?.steps || [],
            provisional: true,
            compileState: "waiting_for_connection",
          });
          return;
        }
        if (disposition === "unavailable") {
          throw new Error(run.error || "AURA could not resume planning after the connection was verified.");
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    } catch (error) {
      const latest = await getPythonRun(runId).catch(() => null);
      const authoritative = latest && planningDisposition(latest) === "connection"
        ? uiConnectionPlanFromRun(latest, interpretation)
        : null;
      setPlan((current) => ({
        ...(current || { interpretation, workflowName: "", steps: [] }),
        ...(authoritative || {}),
        steps: authoritative?.steps?.length ? authoritative.steps : (current?.steps || []),
        provisional: true,
        compileState: authoritative ? "waiting_for_connection" : "blocked",
        compileError: error?.message || "AURA couldn't resume executable validation right now.",
      }));
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

  const keepPlanStartFailureInReview = useCallback((message) => {
    setPlan((previous) => ({
      ...(previous || { interpretation, steps: [] }),
      error: "",
      startError: message || "AURA couldn't validate this plan for execution. Review it and try again.",
    }));
    setPhase("plan");
  }, [interpretation]);

  const ensureSavedWorkflowRun = async () => {
    if (currentRunIdRef.current) return currentRunIdRef.current;
    if (historySavePromiseRef.current) return historySavePromiseRef.current;

    historySavePromiseRef.current = (async () => {
      let workflowId = currentWorkflowIdRef.current;
      let savedWorkflow = null;
      const now = new Date().toISOString();
      const name = workflowName || plan?.workflowName || originalPromptRef.current.slice(0, 60) || "Workflow";
      const workflowUpdate = {
        steps: approvedStepsRef.current,
        interpretation: plan?.interpretation || interpretation,
        last_run_status: "running",
        last_run_date: now,
      };

      if (!workflowId) {
        const [existing] = await aura.entities.Workflow
          .filter({ prompt: originalPromptRef.current }, "-created_date", 1)
          .catch(() => []);
        if (existing) {
          workflowId = existing.id;
          savedWorkflow = await aura.entities.Workflow.update(existing.id, {
            ...workflowUpdate,
            run_count: (Number(existing.run_count) || 0) + 1,
          });
        } else {
          savedWorkflow = await aura.entities.Workflow.create({
            name,
            prompt: originalPromptRef.current,
            ...workflowUpdate,
            run_count: 1,
          });
          workflowId = savedWorkflow.id;
        }
        currentWorkflowIdRef.current = workflowId;
      } else {
        const [existing] = await aura.entities.Workflow.filter({ id: workflowId }, "-created_date", 1);
        savedWorkflow = await aura.entities.Workflow.update(workflowId, {
          ...workflowUpdate,
          ...(workflowName ? { name: workflowName } : {}),
          run_count: (Number(existing?.run_count) || 0) + 1,
        });
      }

      const savedRun = await aura.entities.WorkflowRun.create({
        backend_run_id: pythonRunIdRef.current,
        workflow_id: workflowId,
        prompt: originalPromptRef.current,
        title: name,
        status: "running",
        steps: approvedStepsRef.current,
        backend_created_at: now,
        backend_updated_at: now,
      });
      currentRunIdRef.current = savedRun.id;
      announceWorkflowHistoryChanged({ workflow: savedWorkflow, run: savedRun });
      return savedRun.id;
    })();

    try {
      return await historySavePromiseRef.current;
    } finally {
      historySavePromiseRef.current = null;
    }
  };

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
      if (plan?.provisional && plan.compileState !== "blocked") {
        queuedPlanStartRef.current = { name };
        setPhase("executing");
        setStartTime(Date.now());
        setCurrentStepIdx(0);
        setExecSteps(steps.map((step, index) => ({
          tool: step.tool,
          action: step.title || step.action,
          riskLevel: step.riskLevel,
          status: index === 0 ? "running" : "pending",
          liveOutput: index === 0
            ? "→ Starting now; AURA is finishing technical preparation backstage"
            : "",
        })));
        return;
      }
      keepPlanInReview();
      return;
    }
    if (autoApprove) {
      startPythonExecution();
      return;
    }
    startPythonExecution();
  }, [editRunMode, autoApprove, keepPlanInReview, plan]);

  const handlePreviewApprove = useCallback((editedSteps) => {
    setPreviewError("");
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
      const recoveryMessage = recoveryProgressMessage(run, step);
      return {
        id: step.id,
        stepKey: step.key,
        tool: planned?.tool || planToolName(step),
        action: planned?.title || planned?.action || friendlyStepTitle(step),
        riskLevel: step.consequential ? "modify" : "read",
        status: preflightRetrying ? "recovering" : visibleRecoveryStepStatus(run, step),
        started_at: step.started_at,
        completed_at: step.completed_at,
        liveOutput: preflightRetrying
          ? `→ ${run.automation_state.message || "AURA is retrying a temporary preflight failure automatically"}`
          : recoveryMessage
          ? `→ ${recoveryMessage}`
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
      if (needsRecovery(latest.public_status || latest.status)) showRunRecovery(latest);
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
      if (needsRecovery(latest.public_status || latest.status)) {
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
          if (needsRecovery(resumed.public_status || resumed.status)) {
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

  const startPythonExecution = async (editedUiSteps = null, prepared = false, observeOnly = false) => {
    const runId = pythonRunIdRef.current;
    if (!runId || !pythonPlanRef.current) return;
    try {
      await ensureSavedWorkflowRun();
    } catch (error) {
      console.error("Could not save workflow history", error);
      keepPlanInReview("AURA couldn't save this workflow yet, so it has not started. Please try again.");
      return;
    }
    const generation = ++pythonPollGenerationRef.current;
    setPlan((previous) => previous ? { ...previous, startError: "" } : previous);
    setPhase("executing");
    setStartTime(Date.now());
    const reviewedPlan = {
      ...pythonPlanRef.current,
      steps: pythonPlanRef.current.steps.map((step, index) => {
        const ui = editedUiSteps?.[index];
        if (!ui) return step;
        return { ...step, arguments: editedArgumentsForStep(ui) };
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
        await approvePythonPlan(runId, reviewedPlan.steps);
      }
      for (;;) {
        const run = await getPythonRunResilient(runId, generation);
        if (!run) return;
        setExecSteps(mapRuntimeSteps(run));
        const active = (run.steps || []).findIndex((step) => step.status === "running");
        if (active >= 0) setCurrentStepIdx(active);
        if (run.status === "completed") {
          forgetActivePythonRun(runId);
          const stepKeysById = new Map(
            (run.steps || []).map((step) => [step.id, step.key])
          );
          const outputs = (run.result?.outputs || []).map((output) => ({
            ...output,
            step_key: output.step_key || stepKeysById.get(output.step_id),
          }));
          const synthesis = run.result?.unified_deliverable || {};
          const resultPresentation = run.result?.result_presentation || null;
          const primaryResult = primaryResultFromOutputs(outputs, {
            title: run.plan?.name || "Workflow completed",
            summary: synthesis.summary,
            deliverable: synthesis.deliverable,
          }, resultPresentation);
          finishExecution({
            title: primaryResult.completionTitle || run.plan?.name || "Workflow completed",
            summary: primaryResult.completionSummary || synthesis.summary || "AURA completed the requested workflow.",
            metrics: resultPresentation?.metrics || [],
            resultPresentation,
            primaryResult,
            outcomes: [{
              type: "document",
              title: "Result",
              detail: synthesis.deliverable || synthesis.summary || "The workflow completed successfully.",
              items: [{
                label: "Summary",
                detail: synthesis.deliverable || synthesis.summary || "The workflow completed successfully.",
              }],
              link: primaryResult.link,
              linkLabel: primaryResult.linkLabel,
            }],
            nextSteps: [],
          }, null, "completed");
          return;
        }
        if (run.status === "awaiting_approval") {
          const preparedSteps = approvedStepsRef.current.map((step, index) =>
            resolvedApprovalStep(step, run.steps?.[index], planToolName(run.steps?.[index] || step))
          );
          approvedStepsRef.current = preparedSteps;
          setApprovedSteps(preparedSteps);
          setPhase("preview");
          return;
        }
        if (needsRecovery(run.public_status || run.status)) {
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
      if (prepared && [409, 422].includes(error?.status)) {
        const latest = await getPythonRun(runId).catch(() => null);
        if (latest?.status === "awaiting_approval") {
          const refreshed = approvedStepsRef.current.map((step, index) =>
            resolvedApprovalStep(step, latest.steps?.[index], planToolName(latest.steps?.[index] || step))
          );
          approvedStepsRef.current = refreshed;
          setApprovedSteps(refreshed);
          setPreviewError(error.message || "Review the highlighted values and try again.");
          setPhase("preview");
          return;
        }
      }
      if (!prepared && !observeOnly) {
        const latest = await getPythonRun(runId).catch(() => null);
        const startFailure = approvalStartFailure(latest, error);
        if (startFailure) {
          keepPlanStartFailureInReview(startFailure.message);
          return;
        }
      }
      await recoverRunStatus();
    }
  };

  startPythonExecutionRef.current = startPythonExecution;

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

    let updatedRun = null;
    let updatedWorkflow = null;
    if (currentRunIdRef.current) {
      try {
        updatedRun = await aura.entities.WorkflowRun.update(currentRunIdRef.current, {
          status: executionStatus === "failed" || errorMsg ? "failed" : "completed",
          title: workflowName || res.title,
          summary: res.summary,
          metrics: res.metrics,
          outcomes: res.outcomes,
          steps: approvedStepsRef.current,
          duration_seconds: startTime ? (Date.now() - startTime) / 1000 : null,
          backend_updated_at: new Date().toISOString(),
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
        const updated = await aura.entities.Workflow.updateMany(
          { id: currentWorkflowIdRef.current },
          { $set: wfSet }
        );
        updatedWorkflow = updated[0] || null;
      } catch (e) {
        /* ignore */
      }
    }
    if (updatedRun || updatedWorkflow) {
      announceWorkflowHistoryChanged({ workflow: updatedWorkflow, run: updatedRun });
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
        const run = await aura.entities.WorkflowRun.create({
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
        announceWorkflowHistoryChanged({ workflow: wf, run });
      } catch (e) {
        /* ignore */
      }
    })();
  }, []);

  useEffect(() => {
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
          onBack={phase === "input" ? undefined : handlePageBack}
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
                <PreviewView preview={previewData} steps={approvedSteps} approvalStep={approvalStep} error={previewError} onApprove={handlePreviewApprove} onBack={() => setPhase("plan")} />
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
                    backendRunId={pythonRunIdRef.current}
                    historyWorkflowId={currentWorkflowIdRef.current}
                    scheduleTitle={workflowName || plan?.workflowName}
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
