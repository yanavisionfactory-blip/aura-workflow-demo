import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom/server';
import ShowcaseApp from '../../src/showcase/seo-audit/ShowcaseApp';

export function render(phase, focus = null, initialTour = false) {
  return renderToStaticMarkup(<StaticRouter location="/"><ShowcaseApp initialPhase={phase} initialFocus={focus} initialTour={initialTour}/></StaticRouter>);
}
