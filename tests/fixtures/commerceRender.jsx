import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Results } from '../../src/showcase/commerce-workflow/App.jsx';
import ToolWorkspace from '../../src/showcase/commerce-workflow/ToolWorkspace.jsx';
export const render = packet => renderToStaticMarkup(<Results packet={packet}/>);
export const renderWorkspace = (packet, route) => renderToStaticMarkup(<ToolWorkspace packet={packet} route={route}/>);

import { Plan, Review } from '../../src/showcase/commerce-workflow/WorkflowStages.jsx';
export const renderPlan = () => renderToStaticMarkup(<Plan onNext={() => {}} onBack={() => {}}/>);
export const renderReview = packet => renderToStaticMarkup(<Review packet={packet} onNext={() => {}} onBack={() => {}}/>);
