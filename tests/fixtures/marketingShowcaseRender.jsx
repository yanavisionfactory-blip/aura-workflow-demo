import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {MemoryRouter} from 'react-router-dom';
import ShowcaseApp from '../../src/showcase/marketing-workflow/ShowcaseApp';

export function render(query='') {
  return renderToStaticMarkup(<MemoryRouter initialEntries={[`/${query}`]}><ShowcaseApp/></MemoryRouter>);
}
