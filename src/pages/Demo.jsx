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
import { hydrateConnections } from "@/lib/connectService";
import { getAllConnections } from "@/lib/connectionsStore";
import { approvePythonPlan, createPythonRun, getPythonRun } from "@/lib/auraApi";

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
    setPhase("input");
    setOriginalPrompt("");
    setInterpretation("");
    setPlan(null);
    setResults(null);
    setExecSteps([]);
    setCurrentStepIdx(0);
    setStartTime(null);
    setWorkflowName("");
    setEditRunMode(false);
    setAutoApprove(false);
    editOriginalStepsRef.current = [];
    userSelectedToolsRef.current = [];
  }, []);

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

    // Custom: generate an interpretation first (confirm phase)
    const attachedDocs = (resources && resources.documents) || [];
    setPhase("confirm");
    setInterpretationLoading(true);
    aura.integrations.Core
      .InvokeLLM({
        prompt: `You are AURA, an AI workflow automation platform. A user described a business workflow they want automated.

User request: "${prompt}"
${attachedDocs.length ? `\nThe user attached ${attachedDocs.length} file(s): ${attachedDocs.map((d) => d.name).join(", ")}. Read their contents — they are the source data or context for this workflow.` : ""}

Write ONE clear, conversational sentence restating what they want, as you understood it — plain, specific business language, no jargon, warm tone. This will be shown to the user as "Is this what you meant?" before any plan is built.`,
        response_json_schema: INTERPRETATION_SCHEMA,
        file_urls: attachedDocs.map((d) => d.file_url).filter(Boolean),
      })
      .then((res) => {
        setInterpretation(res.interpretation || "");
        setInterpretationLoading(false);
      })
      .catch(() => {
        setInterpretation(prompt);
        setInterpretationLoading(false);
      });
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
            const created = await createPythonRun(originalPromptRef.current);
            pythonRunIdRef.current = created.id;
            let run;
            for (let attempt = 0; attempt < 120; attempt += 1) {
              run = await getPythonRun(created.id);
              if (run.status === "awaiting_approval" && run.plan?.steps?.length) break;
              if (run.status === "failed") throw new Error(run.error || "Python orchestrator failed");
              await new Promise((resolve) => setTimeout(resolve, 1000));
            }
            if (!run?.plan?.steps?.length) throw new Error("Python orchestrator did not return a plan in time");
            pythonPlanRef.current = run.plan;
            setPlan({
              workflowName: run.plan.name,
              interpretation: run.plan.interpretation,
              estimatedTime: "Runs in the Python control plane",
              steps: run.plan.steps.map((step) => ({
                tool: planToolName(step), title: step.operation, iWill: step.reason, action: step.operation,
                detail: JSON.stringify(step.arguments, null, 2), reason: step.reason, output: step.expected_output,
                flow: [{ label: "Uses", value: planToolName(step) }, { label: "Creates", value: step.expected_output }],
                riskLevel: step.consequential ? "modify" : "read",
                riskNote: step.consequential ? "This provider action runs only after your approval." : "",
                preview: step.consequential ? {
                  type: step.operation === "gmail.send" ? "email" : "list",
                  to: step.arguments?.to || "", subject: step.arguments?.subject || "", body: step.arguments?.body || "",
                  title: step.operation,
                  items: Object.entries(step.arguments || {}).map(([label, value]) => ({ label, detail: JSON.stringify(value) })),
                } : undefined,
              })),
            });
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
    if (pythonRunIdRef.current) startPythonExecution(editedSteps);
    else startExecution();
  }, []);

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
      for (let attempt = 0; attempt < 600; attempt += 1) {
        const run = await getPythonRun(runId);
        setExecSteps((run.steps || []).map((step) => ({
          tool: step.tool_slug, action: step.operation, riskLevel: step.consequential ? "modify" : "read",
          status: step.status,
          liveOutput: step.output?.provider_result ? `→ Provider confirmed ${step.operation}` : step.error ? `→ ${step.error}` : "",
          output: step.output,
        })));
        const active = (run.steps || []).findIndex((step) => step.status === "running");
        if (active >= 0) setCurrentStepIdx(active);
        if (run.status === "completed") {
          const outputs = run.result?.outputs || [];
          finishExecution({
            title: "Workflow completed by Python agents",
            summary: `${run.result?.completed_steps || outputs.length} provider actions completed with stored evidence.`,
            metrics: [{ value: String(run.result?.completed_steps || outputs.length), label: "verified actions" }],
            outcomes: outputs.map((output) => ({
              type: "document", title: output.operation, detail: `Confirmed by ${output.tool}`,
              items: [{ label: "Provider evidence", detail: JSON.stringify(output.provider_result).slice(0, 500) }],
            })),
            nextSteps: [],
          }, null, "completed");
          return;
        }
        if (run.status === "failed" || run.status === "cancelled") throw new Error(run.error || `Workflow ${run.status}`);
        await new Promise((resolve) => setTimeout(resolve, 900));
      }
      throw new Error("Python workflow timed out");
    } catch (error) {
      finishExecution(null, error.message, "failed");
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

  useEffect(() => { hydrateConnections(); }, []);
  useEffect(() => () => clearTimeouts(), []);

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
        <TopBar onHistoryOpen={() => setHistoryOpen(true)} />

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
                  <PlanView plan={plan} hasPreview={!!mock?.preview} onApprove={handleApprove} approveLabel={editRunMode ? "Review changes" : "Start"} userSelectedTools={userSelectedToolsRef.current} />
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

            {phase === "error" && mock?.errorStep && (
              <motion.div
                key="error"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.4 }}
                className="w-full flex justify-center"
              >
                <ErrorView
                  error={mock.errorStep}
                  step={execSteps[mock.errorStep.index]}
                  runSteps={execSteps}
                  onRetry={handleRetry}
                  onEdit={handleEditFromError}
                  onSkip={handleSkip}
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
          <span className="text-[11px] text-muted-foreground/40">AURA v2.5 · Interactive Demo</span>
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
