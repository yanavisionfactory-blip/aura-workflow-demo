import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Check, FileVideo, Film, Loader2, MessageSquare, Pencil, RefreshCw, Save } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { auraRequest } from "@/lib/auraApi";
import { documentMarkdownOptions } from "@/lib/documentMarkdown.mjs";
import { downloadTextFile } from "@/lib/auraDownload";

const prose = "text-sm leading-6 text-slate-300 [&_h1]:mb-4 [&_h1]:text-lg [&_h1]:font-semibold [&_h1]:text-white [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-white [&_h3]:mb-2 [&_h3]:mt-4 [&_h3]:font-medium [&_p]:mb-3 [&_ul]:list-disc [&_ul]:space-y-2 [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:space-y-2 [&_ol]:pl-5 [&_table]:block [&_table]:overflow-auto [&_th]:border [&_th]:border-white/10 [&_th]:p-2 [&_td]:border [&_td]:border-white/10 [&_td]:p-2 [&_a]:text-violet-300 [&_code]:break-all [&_code]:text-xs";
const button = "inline-flex items-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-xs font-medium text-slate-200 transition hover:bg-white/10 disabled:opacity-40";
const timecode = (value) => Number.isFinite(value) && value >= 0 ? `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, "0")}` : null;

function Comments({ file, onSeek }) {
  const [limit, setLimit] = useState(30);
  const comments = file.comments || [];
  const comment = (item, depth = 0) => <article key={item.id} className={`${depth ? "ml-4 border-l border-white/10 pl-3" : "border-b border-white/10 pb-5"} mt-5 text-sm`}>
    <div className="mb-2 flex items-center gap-2"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-500/20 text-xs text-violet-200">{(item.owner?.name || "Reviewer").slice(0, 1)}</span><span className="font-medium text-slate-100">{item.owner?.name || "Reviewer"}</span>{item.completed_at && <span className="ml-auto flex items-center gap-1 text-[10px] text-emerald-300"><Check className="h-3 w-3" />Resolved comment</span>}</div>
    {timecode(item.timestamp) && <button type="button" onClick={() => onSeek(item.timestamp)} className="mb-2 rounded bg-violet-500/15 px-2 py-1 text-xs text-violet-200">{timecode(item.timestamp)}</button>}
    <p className="whitespace-pre-wrap break-words leading-6 text-slate-300">{item.text || "Comment has no text."}</p>
    {item.page != null && <p className="mt-2 text-xs text-slate-500">Page {item.page}</p>}
    {item.attachments?.length > 0 && <p className="mt-2 text-xs text-slate-400">{item.attachments.length} attachment(s) · open in Frame.io</p>}
    {depth < 8 && (item.replies || []).map((reply) => comment(reply, depth + 1))}
  </article>;
  return <div className="p-5">
    {!file.commentsComplete && <p role="status" className="mb-4 rounded-lg bg-amber-400/10 p-3 text-xs leading-5 text-amber-200">The full comment set has not been verified. Refresh the review before making a decision.</p>}
    {comments.length ? <>{comments.slice(0, limit).map((item) => comment(item))}{comments.length > limit && <button type="button" onClick={() => setLimit(limit + 30)} className={`${button} mt-4`}>Show more comments</button>}</>
      : <div className="flex min-h-60 flex-col items-center justify-center text-center"><MessageSquare className="mb-4 h-8 w-8 text-slate-500" /><h3 className="font-medium text-slate-100">{file.commentsComplete ? "No reviewer comments yet" : "Comments not loaded"}</h3><p className="mt-2 max-w-60 text-xs leading-6 text-slate-400">{file.commentsComplete ? "Add feedback in Frame.io, then ask AURA to refresh this review." : "Run the comment read to see feedback for this exact version."}</p></div>}
  </div>;
}

function ReviewBrief({ brief, runId }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(brief.body);
  const [savedBody, setSavedBody] = useState(brief.body);
  const [notice, setNotice] = useState("");
  const key = runId ? `aura-review-draft:${runId}:${brief.sourceStepKey || "brief"}` : null;
  useEffect(() => {
    setDraft(brief.body); setSavedBody(brief.body); setEditing(false); setNotice("");
    if (!key) return;
    try {
      const saved = JSON.parse(localStorage.getItem(key));
      if (saved?.original === brief.body && typeof saved.body === "string") {
        setDraft(saved.body); setSavedBody(saved.body); setNotice("Your edited draft · saved on this device");
      }
    } catch { /* The saved provider result remains the default. */ }
  }, [key, brief.body]);
  const save = () => {
    try {
      if (key) localStorage.setItem(key, JSON.stringify({ original: brief.body, body: draft }));
      setSavedBody(draft); setEditing(false);
      setNotice(key ? "Your edited draft · saved on this device" : "Your edited draft · download to keep a copy");
    } catch { setNotice("The draft could not be saved on this device. Download a copy to keep your edits."); }
  };
  // Identity/provenance remains available in the complete brief and file
  // details; the review panel leads with the actual findings and next actions.
  const readable = savedBody.split(/(?=^##\s)/m).filter((section) => !/^##\s+[^\n]*(?:intake|provenance|verified filename)/i.test(section)).join("");
  return <div className="p-5">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><span className="text-[10px] font-semibold uppercase tracking-wider text-violet-300">AURA draft · approval pending</span><button type="button" onClick={() => setEditing(!editing)} className={button}><Pencil className="h-3.5 w-3.5" />{editing ? "View brief" : "Edit brief"}</button></div>
    {notice && <p role="status" className="mb-3 text-xs leading-5 text-violet-200">{notice}</p>}
    {editing ? <><label className="mb-2 block text-xs text-slate-400" htmlFor="frameio-brief-editor">Revision brief</label><textarea id="frameio-brief-editor" value={draft} onChange={(event) => setDraft(event.target.value)} rows={18} className="w-full resize-y rounded-lg border border-violet-400/40 bg-[#11131c] p-4 text-sm leading-6 text-slate-200 outline-none focus:ring-2 focus:ring-violet-400/30" /><div className="mt-3 flex gap-2"><button type="button" onClick={save} disabled={!draft.trim()} className={button}><Save className="h-3.5 w-3.5" />Save draft</button><button type="button" onClick={() => { setDraft(savedBody); setEditing(false); }} className={button}>Cancel</button></div></>
      : <div className={prose}><ReactMarkdown {...documentMarkdownOptions}>{readable}</ReactMarkdown></div>}
    <button type="button" onClick={() => downloadTextFile("frameio-revision-brief.md", editing ? draft : savedBody)} className="mt-5 text-xs font-medium text-violet-300 underline underline-offset-4">Download complete brief</button>
  </div>;
}

export default function FrameioReviewResult({ result, backendRunId }) {
  const [fileKey, setFileKey] = useState(result.files[0]?.key);
  const file = result.files.find((item) => item.key === fileKey) || result.files[0];
  const [tab, setTab] = useState(result.brief ? "brief" : "comments");
  const [media, setMedia] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mediaError, setMediaError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const video = useRef(null);
  useEffect(() => {
    let active = true;
    setMedia(null); setMediaError("");
    if (!backendRunId || !file.sourceStepKey) return;
    setLoading(true);
    auraRequest(`/v1/runs/${encodeURIComponent(backendRunId)}/steps/${encodeURIComponent(file.sourceStepKey)}/frameio-screen`, { timeoutMs: 25000 })
      .then((screen) => {
        if (screen.file_id !== file.fileId || screen.account_id !== file.accountId) throw new Error("File does not match the review");
        if (active) setMedia(screen);
      })
      .catch(() => { if (active) setMediaError("Preview unavailable. You can still open this file in Frame.io."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [backendRunId, file.sourceStepKey, file.fileId, file.accountId, refresh]);
  const isVideo = /\.(mp4|mov|m4v|webm|mxf|avi)$/i.test(file.name);
  const isAudio = /\.(mp3|wav|aac|m4a|ogg)$/i.test(file.name);
  const canPlay = media?.playback_url && !mediaError && (isVideo || isAudio);
  return <section aria-label="Frame.io review workspace" className="overflow-hidden rounded-2xl border border-white/10 bg-[#171820] text-slate-100 shadow-2xl">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-4">
      <div className="flex min-w-0 items-center gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-violet-500/20 text-violet-300"><Film className="h-5 w-5" /></span><div className="min-w-0"><p className="text-sm font-semibold">Frame.io</p><p className="truncate text-xs text-slate-400">{file.name}</p></div></div>
      <div className="flex flex-wrap items-center gap-2"><span className="rounded-full border border-amber-300/20 bg-amber-300/5 px-3 py-1.5 text-[10px] text-amber-200">Human review pending</span>{file.link && <a href={file.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-lg bg-violet-500 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-400">Open in Frame.io<ArrowUpRight className="h-3.5 w-3.5" /></a>}</div>
    </header>
    {result.files.length > 1 && <div role="tablist" aria-label="Review files" className="flex gap-2 overflow-x-auto border-b border-white/10 p-3">{result.files.map((item) => <button type="button" role="tab" aria-selected={item.key === file.key} onClick={() => setFileKey(item.key)} key={item.key} className={`${button} ${item.key === file.key ? "bg-violet-500/20 text-violet-200" : ""}`}>{item.name}</button>)}</div>}
    <div className="grid min-w-0 lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,1fr)]">
      <div className="min-w-0 bg-[#0c0d12]">
        <div className="flex aspect-video min-h-56 items-center justify-center bg-black/30 p-3 sm:min-h-80">
          {loading ? <div role="status" className="flex flex-col items-center gap-3 text-sm text-slate-400"><Loader2 className="h-6 w-6 animate-spin text-violet-400" />Loading your Frame.io preview…</div>
            : canPlay ? isAudio ? <audio ref={video} controls src={media.playback_url} onError={() => setMediaError("Audio preview unavailable. Open the file in Frame.io.")} className="w-full" />
              : <video ref={video} controls playsInline preload="metadata" poster={media.thumbnail_url || undefined} src={media.playback_url} onError={() => setMediaError("Video preview unavailable. Open the file in Frame.io.")} className="max-h-[65vh] w-full object-contain" aria-label={`Frame.io video: ${file.name}`} />
              : media?.thumbnail_url && !mediaError ? <img src={media.thumbnail_url} alt={`Frame.io preview of ${file.name}`} onError={() => setMediaError("Thumbnail unavailable. Open the file in Frame.io.")} className="max-h-[65vh] w-full object-contain" />
                : <div className="max-w-xs p-6 text-center"><FileVideo className="mx-auto mb-4 h-10 w-10 text-slate-600" /><p className="text-sm font-medium">{file.name}</p><p className="mt-3 text-xs leading-6 text-slate-400">{mediaError || "Open the original file in Frame.io to review its media."}</p>{file.link && <a href={file.link} target="_blank" rel="noopener noreferrer" className={`${button} mt-4`}>View original<ArrowUpRight className="h-3.5 w-3.5" /></a>}</div>}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-y border-white/10 px-5 py-3 text-xs text-slate-400"><span>{media?.silent_preview ? "Silent preview · review audio in Frame.io" : "Exact file version from this workflow"}</span>{backendRunId && file.sourceStepKey && <button type="button" disabled={loading} onClick={() => setRefresh((value) => value + 1)} className="flex items-center gap-1.5 text-violet-300"><RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />Refresh preview</button>}</div>
        <div className="p-5"><p className="text-sm font-medium">Review the file, then refine the brief</p><p className="mt-2 text-xs leading-6 text-slate-400">Use Frame.io for reviewer comments and version changes. Edit the AURA brief here, or describe a change below.</p><details className="mt-5 text-xs text-slate-400"><summary className="cursor-pointer font-medium">File details</summary><dl className="mt-3 space-y-3 break-all"><div><dt>File version</dt><dd className="mt-1 text-slate-300">{file.fileId}</dd></div><div><dt>Project</dt><dd className="mt-1 text-slate-300">{file.projectId || "Not returned"}</dd></div><div><dt>Comments checked</dt><dd className="mt-1 text-slate-300">{file.commentsComplete ? `${file.commentCount} · complete read` : "Not fully verified"}</dd></div></dl></details></div>
      </div>
      <aside className="min-w-0 border-t border-white/10 lg:border-l lg:border-t-0">
        <div role="tablist" aria-label="Frame.io review panels" className="flex gap-5 border-b border-white/10 px-5">{[["comments", `Comments${file.commentsComplete ? ` (${file.commentCount})` : ""}`], ...(result.brief ? [["brief", "Revision brief"]] : [])].map(([id, label]) => <button type="button" role="tab" aria-selected={tab === id} key={id} onClick={() => setTab(id)} className={`border-b-2 py-4 text-xs font-medium ${tab === id ? "border-violet-400 text-white" : "border-transparent text-slate-400 hover:text-white"}`}>{label}</button>)}</div>
        <div className="max-h-[min(74vh,800px)] min-h-80 overflow-auto" role="tabpanel" aria-label={tab === "brief" ? "Revision brief" : "Frame.io comments"}>{tab === "brief" && result.brief ? <ReviewBrief brief={result.brief} runId={backendRunId} /> : <Comments key={file.key} file={file} onSeek={(seconds) => { if (video.current) video.current.currentTime = seconds; }} />}</div>
      </aside>
    </div>
  </section>;
}
