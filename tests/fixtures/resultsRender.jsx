import { renderToStaticMarkup } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import ResultsView from "../../src/components/aura/ResultsView";
import { savedRunResults } from "../../src/lib/savedRunResults.mjs";
import MarketingToolResults from "../../src/components/aura/MarketingToolResults";

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
