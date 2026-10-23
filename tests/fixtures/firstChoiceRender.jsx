import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {MemoryRouter} from 'react-router-dom';
import App from '../../src/showcase/first-choice-seo/App';
export function render(query='?screen=results'){return renderToStaticMarkup(<MemoryRouter initialEntries={['/'+query]}><App/></MemoryRouter>);}
