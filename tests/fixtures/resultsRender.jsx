import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import ResultsView from "../../src/components/aura/ResultsView";
import { savedRunResults } from "../../src/lib/savedRunResults.mjs";
import MarketingToolResults from "../../src/components/aura/MarketingToolResults";
import SheetActionReview, { PreparedReports, SheetReviewCard } from "../../src/components/aura/SheetActionReview";
import PreviewView from "../../src/components/aura/PreviewView";
import ToolActionScreen from "../../src/components/aura/ToolActionScreen";
import ExecutionView from "../../src/components/aura/ExecutionView";
import ToolOutputReview from "../../src/components/aura/ToolOutputReview";
import PlanView from "../../src/components/aura/PlanView";
import { plannedApprovalStep } from "../../src/lib/approvalReview.mjs";

export function renderActionScreen(step, editing = false) {
  return renderToStaticMarkup(<ToolActionScreen step={step} args={step.arguments} editing={editing} onChange={() => {}} />);
}

export function renderExecution(steps, review = null) {
  return renderToStaticMarkup(review ? <ToolOutputReview steps={steps} review={review} onApprove={() => {}} />
    : <ExecutionView steps={steps} currentStepIndex={0} isReal />);
}

export function renderPlan(steps) {
  return renderToStaticMarkup(<PlanView plan={{ workflowName: "KPI dashboard", steps }} onApprove={() => {}} />);
}

export function renderApproval(steps) {
  return renderToStaticMarkup(<PreviewView prepared steps={steps.map((step) => plannedApprovalStep(
    { ...step, riskLevel: "modify" }, { ...step, consequential: true }, step.tool,
  ))} onApprove={() => {}} onBack={() => {}} />);
}

export function renderSheetCard(args, canEdit = true) {
  return renderToStaticMarkup(<SheetReviewCard args={args} contract={{ fields: [{ key: "values", editable: canEdit }] }} onChange={() => {}} />);
}

export function renderSheetReview(args, activity = [], editing = false, canEdit = true) {
  return renderToStaticMarkup(<><PreparedReports activity={activity} /><SheetActionReview args={args} activity={activity} editing={editing} canEdit={canEdit} onChange={() => {}} /></>);
}

export function renderToolWorkspace(packet, activity, initialTool, initialSection) {
  return renderToStaticMarkup(<MarketingToolResults packet={packet} activity={activity} initialTool={initialTool} initialSection={initialSection} compact />);
}

export function ResultsTestView({ run, ...callbacks }) {
  const activity = run.steps.map((step) => ({ ...step, stepKey: step.key,
    tool: step.tool_slug, action: step.reason,
  }));
  return <StaticRouter location={`/runs/${run.id}`}>
    <ResultsView results={savedRunResults(run)} activity={activity}
      backendRunId={run.id} prompt={run.prompt} onNewWorkflow={() => {}} onStartWorkflow={() => {}} {...callbacks} />
  </StaticRouter>;
}

export function render(run) { return renderToStaticMarkup(<ResultsTestView run={run} />); }
