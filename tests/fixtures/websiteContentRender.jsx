import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import WebsiteContentResult from '../../src/components/aura/WebsiteContentResult';

export function render(packet, options = {}) {
  return renderToStaticMarkup(<MemoryRouter><WebsiteContentResult packet={packet} {...options}/></MemoryRouter>);
}
