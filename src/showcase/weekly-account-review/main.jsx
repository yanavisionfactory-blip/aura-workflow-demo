import React from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import ShowcaseApp from './ShowcaseApp';
import '@/index.css';
import '../seo-audit/showcase.css';

const params = new URLSearchParams(window.location.search);
createRoot(document.getElementById('root')).render(<React.StrictMode><MemoryRouter><ShowcaseApp initialPhase={params.get('screen')} initialTour={params.get('tour') === '1'}/></MemoryRouter></React.StrictMode>);
