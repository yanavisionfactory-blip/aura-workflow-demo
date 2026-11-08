import { useEffect, useRef, useState } from "react";
import { auraRequest } from "@/lib/auraApi";

const safeCanvaUrl = (value) => {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && (!url.port || url.port === "443")
      && (url.hostname === "canva.com" || url.hostname.endsWith(".canva.com"));
  } catch { return false; }
};

// Signed Canva thumbnails expire. Read the existing design on every report visit;
// the saved receipt remains evidence, not a permanent media URL.
export default function CanvaResult({ result, backendRunId, onCanvaScreen, children }) {
  const [screen, setScreen] = useState(null);
  const [loading, setLoading] = useState(false);
  const [failedUrl, setFailedUrl] = useState(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const automaticRetry = useRef(false);
  const callback = useRef(onCanvaScreen);
  callback.current = onCanvaScreen;
  const canRefresh = Boolean(backendRunId && result.sourceStepKey && result.designId);
  useEffect(() => {
    if (!canRefresh) return;
    let active = true;
    setLoading(true); setError(false);
    auraRequest(`/v1/runs/${encodeURIComponent(backendRunId)}/steps/${encodeURIComponent(result.sourceStepKey)}/canva-screen`, { timeoutMs: 25000 })
      .then((fresh) => {
        if (fresh.designId !== result.designId || !safeCanvaUrl(fresh.thumbnailUrl)) throw new Error("Canva preview does not match");
        const safe = { designId: fresh.designId, thumbnailUrl: fresh.thumbnailUrl,
          ...(safeCanvaUrl(fresh.link) ? { link: fresh.link } : {}),
          ...(safeCanvaUrl(fresh.viewLink) ? { viewLink: fresh.viewLink } : {}) };
        if (active) { setScreen(safe); setFailedUrl(null); callback.current?.(safe); }
      })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [backendRunId, result.sourceStepKey, result.designId, canRefresh, refresh]);
  const thumbnailUrl = screen?.thumbnailUrl || result.thumbnailUrl;
  const failed = !thumbnailUrl || failedUrl === thumbnailUrl;
  const imageFailed = () => {
    setFailedUrl(thumbnailUrl);
    if (canRefresh && !loading && !automaticRetry.current) {
      automaticRetry.current = true;
      setRefresh((value) => value + 1);
    }
  };
  return <div>
    {children ? children(thumbnailUrl, imageFailed) : !failed
      ? <img key={thumbnailUrl} src={thumbnailUrl} onError={imageFailed} alt={`Finished Canva design: ${result.title}`} className="block w-full rounded-2xl border border-white/10 bg-[#101c2c] object-contain" />
      : <div role="status" className="flex min-h-44 items-center justify-center rounded-2xl border border-white/10 bg-[#101c2c] px-6 text-center text-sm text-[#b7c7d9]">{loading ? "Loading your Canva design…" : "The Canva preview could not load. Your saved design is unchanged."}</div>}
    {canRefresh && (failed || error) && !loading && <button type="button" onClick={() => setRefresh((value) => value + 1)} className="mt-3 rounded-lg border border-white/15 px-4 py-2 text-sm text-cyan-200 hover:bg-white/5">Retry Canva preview</button>}
  </div>;
}
