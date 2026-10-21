import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import SimulatedCMSScreen from '@/components/aura/SimulatedCMSScreen';
import { getPythonRun } from '@/lib/auraApi';
import { savedRunResults } from '@/lib/savedRunResults.mjs';
import { cmsToolScreenPath, websiteCMSPreview } from '@/lib/websiteCMSPreview.mjs';

export default function SimulatedCMSTool() {
  const { runId, toolSlug } = useParams();
  const [run, setRun] = useState(null);
  const [error, setError] = useState('');
  const valid = Boolean(cmsToolScreenPath(runId, `${toolSlug}-preview`));
  const backHref = `/runs/${encodeURIComponent(runId)}`;
  useEffect(() => {
    let active = true;
    setRun(null); setError('');
    if (!valid) { setError('This simulated tool screen is unavailable.'); return undefined; }
    // Read only the same tenant-scoped saved run as AURA Results. No CMS calls.
    getPythonRun(runId).then((value) => { if (active) setRun(value); })
      .catch(() => { if (active) setError('These saved drafts are unavailable in this workspace.'); });
    return () => { active = false; };
  }, [runId, valid]);
  const view = useMemo(() => {
    if (!run) return null;
    const result = savedRunResults(run).primaryResult;
    if (run.status !== 'completed' || result.kind !== 'website_content') return null;
    const bundle = websiteCMSPreview(result.packet);
    return { client: bundle.client, output: bundle.tools.find((item) => item.id === `${toolSlug}-preview`) };
  }, [run, toolSlug]);
  if (view?.output) return <SimulatedCMSScreen key={`${runId}-${toolSlug}`} client={view.client} output={view.output} backHref={backHref}/>;
  return <main className="grid min-h-screen place-items-center bg-[#f0f0f1] p-8 text-center text-[#1d2327]"><div><h1 className="text-xl font-semibold">Simulated CMS workspace</h1><p role={error || run ? 'alert' : 'status'} className="mt-4 text-sm">{error || (run ? 'A completed five-page content package is required.' : 'Opening the saved workflow drafts…')}</p><Link to={backHref} className="mt-5 inline-block text-sm text-[#2271b1] underline">Back to AURA results</Link></div></main>;
}
