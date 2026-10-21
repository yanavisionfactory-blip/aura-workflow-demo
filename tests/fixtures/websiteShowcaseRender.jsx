import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {MemoryRouter} from 'react-router-dom';
import ShowcaseApp from '../../src/showcase/website-content/ShowcaseApp';
export function render(query='?screen=results'){return renderToStaticMarkup(<MemoryRouter initialEntries={[`/${query}`]}><ShowcaseApp/></MemoryRouter>);}
