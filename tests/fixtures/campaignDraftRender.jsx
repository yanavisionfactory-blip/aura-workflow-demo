import { renderToStaticMarkup } from 'react-dom/server';
import CampaignDraftSetup from '../../src/components/aura/CampaignDraftSetup';
import CampaignDraftResult from '../../src/components/aura/CampaignDraftResult';

export function renderSetup() {
  return renderToStaticMarkup(<CampaignDraftSetup onSubmit={() => {}} onBack={() => {}} />);
}
export function renderResult(result) {
  return renderToStaticMarkup(<CampaignDraftResult result={result} />);
}
