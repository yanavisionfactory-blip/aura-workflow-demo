import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom/server';
import ShowcaseApp from '../../src/showcase/weekly-account-review/ShowcaseApp';
import WeeklyReviewResult, { CreativeDraft } from '../../src/components/aura/WeeklyReviewResult';
import packet from '../../src/showcase/weekly-account-review/data.mjs';

export function render(phase, focus = null, initialTour = false) {
  return renderToStaticMarkup(<StaticRouter location="/"><ShowcaseApp initialPhase={phase} initialFocus={focus} initialTour={initialTour}/></StaticRouter>);
}
export function renderCreative(id, initialVariant) {
  return renderToStaticMarkup(<CreativeDraft packet={packet} creative={packet.creatives.find((item) => item.id === id)} onEvidence={() => {}} initialVariant={initialVariant}/>);
}

export function renderExecuted(input, focus = null) {
  return renderToStaticMarkup(<StaticRouter location="/"><WeeklyReviewResult packet={input} focus={focus}/></StaticRouter>);
}
