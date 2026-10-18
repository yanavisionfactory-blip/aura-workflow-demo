import { lazy, Suspense } from "react";
import ReactMarkdown from "react-markdown";
import { articleMarkdown, articleWordCount, jiraDocument, jiraText } from "@/lib/actionContent.mjs";
import "react-quill/dist/quill.snow.css";

const RichTextEditor = lazy(() => import("react-quill"));
const articleModules = { toolbar: [[{ header: [2, 3, false] }], ["bold", "italic"], [{ list: "ordered" }, { list: "bullet" }], ["link"], ["clean"]] };
const inputClass = "w-full rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm outline-none focus:border-primary";

export function ArticleActionReview({ args, editing, onChange }) {
  return <section aria-label="Article preview" className="space-y-4">
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="rounded-full bg-emerald-400/10 px-3 py-1.5 text-emerald-200">Unpublished draft</span>
      <span className="text-muted-foreground">{articleWordCount(args.content)} words · existing WordPress article</span>
    </div>
    {editing ? <>
      <label className="block space-y-2"><span className="text-sm">Article title</span><input aria-label="Article title" className={inputClass} value={args.title || ""} onChange={(event) => onChange({ ...args, title: event.target.value })} /></label>
      <Suspense fallback={<p className="text-sm text-muted-foreground">Opening the article editor…</p>}>
        <div className="aura-article-editor"><RichTextEditor theme="snow" value={args.content || ""} onChange={(content) => onChange({ ...args, content })} modules={articleModules} /></div>
      </Suspense>
    </> : <article className="aura-article-preview rounded-xl border border-white/10 bg-white/[0.02] p-5 text-sm leading-7">
      <h2 className="mb-5 text-xl font-semibold">{args.title}</h2>
      <ReactMarkdown>{articleMarkdown(args.content)}</ReactMarkdown>
    </article>}
    <p className="text-xs text-muted-foreground">Approval saves this article as a draft. It does not publish it.</p>
  </section>;
}

export function SeoActionReview({ args, editing, onChange }) {
  return <section aria-label="SEO preview" className="space-y-4">
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-5"><p className="text-lg text-sky-300">{args.title}</p><p className="mt-2 text-sm text-muted-foreground">{args.description}</p></div>
    {[['title', 'SEO title', 60], ['description', 'Search description', 160], ['focus_keyword', 'Focus keyword', null]].map(([key, label, guide]) => <label key={key} className="block space-y-2"><span className="flex justify-between text-sm">{label}{guide && <span className="text-xs text-muted-foreground">{String(args[key] || "").length} characters · about {guide} recommended</span>}</span>{key === 'description' ? <textarea className={inputClass} rows={3} readOnly={!editing} value={args[key] || ""} onChange={(event) => onChange({ ...args, [key]: event.target.value })} /> : <input className={inputClass} readOnly={!editing} value={args[key] || ""} onChange={(event) => onChange({ ...args, [key]: event.target.value })} />}</label>)}
    <p className="text-xs text-muted-foreground">AURA will save these settings and check them again. No new SEO score is promised.</p>
  </section>;
}

export function JiraUpdateReview({ args, editing, onChange }) {
  return <section aria-label="Task update preview" className="space-y-4">
    <p className="text-sm text-muted-foreground">Update the existing handoff task. Its identity and other details stay the same.</p>
    {Object.hasOwn(args.fields || {}, "summary") && <label className="block space-y-2"><span className="text-sm">Task title</span><input className={inputClass} readOnly={!editing} value={args.fields.summary} onChange={(event) => onChange({ ...args, fields: { ...args.fields, summary: event.target.value } })} /></label>}
    {Object.hasOwn(args.fields || {}, "description") && <label className="block space-y-2"><span className="text-sm">Handoff details</span><textarea className={inputClass} rows={14} readOnly={!editing} value={jiraText(args.fields.description).trimEnd()} onChange={(event) => onChange({ ...args, fields: { ...args.fields, description: jiraDocument(event.target.value) } })} /></label>}
    {Array.isArray(args.fields?.labels) && <p className="text-sm">Labels: {args.fields.labels.join(", ")}</p>}
  </section>;
}
