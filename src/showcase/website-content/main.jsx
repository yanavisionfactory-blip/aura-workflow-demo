import React from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import ShowcaseApp from './ShowcaseApp';
import '@/index.css';
import './showcase.css';
createRoot(document.getElementById('root')).render(<React.StrictMode><BrowserRouter><ShowcaseApp/></BrowserRouter></React.StrictMode>);
