import { useState } from "react";
import { ChevronDown, ExternalLink, FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { articleMarkdown } from "@/lib/actionContent.mjs";
import { deliveryLink } from "@/lib/workflowDelivery.mjs";

export default function ArticleResultPreview({ articles }) {
  const [selected, setSelected] = useState("0");
  const [expanded, setExpanded] = useState(false);
  const article = articles[Number(selected)] || articles[0];
  const link = deliveryLink(article.link);
  return (
    <Tabs value={selected} onValueChange={(value) => { setSelected(value); setExpanded(false); }}>
      {articles.length > 1 && <div className="mb-4 overflow-x-auto">
        <TabsList aria-label="Article locations" className="h-auto min-w-max bg-black/15 p-1">
          {articles.map((item, index) => <TabsTrigger key={index} value={String(index)} className="px-4 py-2 text-xs data-[state=active]:bg-primary/20 data-[state=active]:text-primary">{item.location || `Article ${index + 1}`}<span className="ml-2 text-[10px] opacity-60">{item.words.toLocaleString()} words</span></TabsTrigger>)}
        </TabsList>
      </div>}
      <TabsContent value={selected} className="mt-0">
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0b1422]">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-4 py-3 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-2"><FileText className="h-3.5 w-3.5 text-emerald-400" />Unpublished WordPress draft · {article.words.toLocaleString()} words</span>
            {link && <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-primary hover:underline">Open draft<ExternalLink className="h-3 w-3" /></a>}
          </div>
          <div key={selected} role="region" aria-label={`${article.location || "Article"} article content`} tabIndex={0} className={`${expanded ? "" : "max-h-[28rem] overflow-y-auto"} bg-[#f8fafc] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary`}>
            <article className="aura-article-document mx-auto max-w-3xl px-6 py-8 text-slate-700 sm:px-10 sm:py-10">
              <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-violet-600">{article.location || "Homeowner guide"} · Demonstration article</p>
              <h3 className="mb-6 text-2xl font-semibold leading-tight text-slate-900 sm:text-3xl">{article.title}</h3>
              <div className="aura-article-preview text-sm leading-7"><ReactMarkdown>{articleMarkdown(article.body)}</ReactMarkdown></div>
            </article>
          </div>
          <button type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded} className="flex w-full items-center justify-center gap-2 border-t border-white/10 px-4 py-3 text-xs text-primary hover:bg-white/5"><ChevronDown className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-180" : ""}`} />{expanded ? "Collapse article" : "Read full article"}</button>
        </div>
      </TabsContent>
    </Tabs>
  );
}
