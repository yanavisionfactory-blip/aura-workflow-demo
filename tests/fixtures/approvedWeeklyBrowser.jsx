import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import WeeklyReviewSetup from '../../src/components/aura/WeeklyReviewSetup';
import ApprovedWeeklyReviewResult from '../../src/components/aura/ApprovedWeeklyReviewResult';
import { testWeeklyPacket } from './approvedWeeklyPacket.mjs';
import '../../src/index.css';
function DevelopmentCheck() {
  const [view, setView] = useState('setup'), [submitted, setSubmitted] = useState('');
  return <main className="min-h-screen bg-background p-5 text-foreground"><div className="mx-auto mb-8 max-w-4xl rounded-xl border border-amber-400/40 bg-amber-400/10 p-4 text-xs text-amber-100"><strong>DEVELOPMENT CHECK · FABRICATED UNIT TEST INPUT · NO CLIENT PERFORMANCE</strong><div className="mt-3 flex gap-4"><button type="button" onClick={() => setView('setup')}>Test input form</button><button type="button" onClick={() => setView('result')}>Test result view</button></div></div><div className="mx-auto max-w-4xl">{view === 'setup' ? <WeeklyReviewSetup onBack={() => setView('result')} onSubmit={(prompt, _tools, resources) => setSubmitted(`${prompt}\n${resources.documents[0].size} bytes received locally; no server request was sent.`)}/> : <ApprovedWeeklyReviewResult packet={testWeeklyPacket()}/>}<pre role="status" className="mt-4 whitespace-pre-wrap text-xs">{submitted}</pre></div></main>;
}
createRoot(document.getElementById('root')).render(<DevelopmentCheck/>);
