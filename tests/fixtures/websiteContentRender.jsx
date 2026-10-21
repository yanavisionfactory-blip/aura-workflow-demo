import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import WebsiteContentResult from '../../src/components/aura/WebsiteContentResult';
import SimulatedCMSScreen from '../../src/components/aura/SimulatedCMSScreen';

export function render(packet, options = {}) {
  return renderToStaticMarkup(<MemoryRouter><WebsiteContentResult packet={packet} runId="test-run" {...options}/></MemoryRouter>);
}

export function renderTool(output, options = {}) {
  return renderToStaticMarkup(<MemoryRouter><SimulatedCMSScreen output={output} client="Example Learning" backHref="/runs/test-run?cmsPreview=simulated" {...options}/></MemoryRouter>);
}
