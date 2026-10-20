import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom/server';
import ExecutiveReviewResult from '../../src/components/aura/ExecutiveReviewResult';

export function render(input, focus = null) {
  return renderToStaticMarkup(<StaticRouter location="/"><ExecutiveReviewResult packet={input} focus={focus}/></StaticRouter>);
}
