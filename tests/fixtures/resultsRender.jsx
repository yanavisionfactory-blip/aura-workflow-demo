import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import ResultsView from "../../src/components/aura/ResultsView";
import { savedRunResults } from "../../src/lib/savedRunResults.mjs";
import MarketingToolResults from "../../src/components/aura/MarketingToolResults";
import SheetActionReview, { PreparedReports, SheetReviewCard } from "../../src/components/aura/SheetActionReview";

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
