import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { Results } from '../../src/showcase/commerce-workflow/App.jsx';
export const render = packet => renderToStaticMarkup(<Results packet={packet}/>);
