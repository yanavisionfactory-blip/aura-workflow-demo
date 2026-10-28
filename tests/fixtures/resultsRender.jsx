import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import ResultsView from "../../src/components/aura/ResultsView";
import { savedRunResults } from "../../src/lib/savedRunResults.mjs";
import MarketingToolResults from "../../src/components/aura/MarketingToolResults";
import SheetActionReview, { PreparedReports, SheetReviewCard } from "../../src/components/aura/SheetActionReview";
import PreviewView from "../../src/components/aura/PreviewView";
import ToolActionScreen from "../../src/components/aura/ToolActionScreen";
import PlanToolWorkspace from "../../src/components/aura/PlanToolWorkspace";
import { plannedApprovalStep } from "../../src/lib/approvalReview.mjs";

export function renderActionScreen(step, editing = false) {
  return renderToStaticMarkup(<ToolActionScreen step={step} args={step.arguments} editing={editing} onChange={() => {}} />);
}

export function renderPlanTools(steps) {
  return renderToStaticMarkup(<PlanToolWorkspace steps={steps} onRevise={() => {}} />);
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

export function render(run) {
  const activity = run.steps.map((step) => ({ ...step, stepKey: step.key,
    tool: step.tool_slug, action: step.reason,
  }));
  return renderToStaticMarkup(<StaticRouter location={`/runs/${run.id}`}>
    <ResultsView results={savedRunResults(run)} activity={activity}
      backendRunId={run.id} onNewWorkflow={() => {}} onStartWorkflow={() => {}} />
  </StaticRouter>);
}
