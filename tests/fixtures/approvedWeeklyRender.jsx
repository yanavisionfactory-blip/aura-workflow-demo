import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import WeeklyReviewSetup from '../../src/components/aura/WeeklyReviewSetup';
import ApprovedWeeklyReviewResult from '../../src/components/aura/ApprovedWeeklyReviewResult';
export const renderSetup = () => renderToStaticMarkup(<WeeklyReviewSetup onSubmit={() => {}} onBack={() => {}}/>);
export const renderResult = (packet, initialSection = 'Summary') => renderToStaticMarkup(<ApprovedWeeklyReviewResult packet={packet} initialSection={initialSection}/>);
