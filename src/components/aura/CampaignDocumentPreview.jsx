import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function CampaignDocumentPreview({ preview, groups }) {
  const [selected, setSelected] = useState("0");
  return <>
    <p className="mb-4 text-xs leading-6 text-muted-foreground">Complete saved campaign copy · Fictional demonstration · All placements unpublished</p>
    <Tabs value={selected} onValueChange={setSelected}>
      <TabsList aria-label="Saved campaign channels" className="mb-5 h-auto flex-wrap justify-start bg-black/15 p-1">{groups.map((g, i) => <TabsTrigger key={g.name} value={String(i)} className="px-4 py-2 text-xs data-[state=active]:bg-primary/20">{g.name}<span className="ml-2 opacity-50">{g.sections.length}</span></TabsTrigger>)}</TabsList>
      {groups.map((g, i) => <TabsContent key={g.name} value={String(i)} className="space-y-4">{g.sections.map((section) => <article key={section.title} className="rounded-2xl bg-slate-50 px-6 py-7 text-slate-700 sm:px-9"><h3 className="mb-5 text-lg font-semibold text-slate-900">{section.title}</h3><div className="aura-article-preview text-sm leading-7"><ReactMarkdown>{section.body}</ReactMarkdown></div></article>)}</TabsContent>)}
    </Tabs>
    <details className="mt-5 rounded-xl border border-white/10 p-5"><summary className="cursor-pointer text-sm text-primary">Brief, checklist and complete saved package</summary><div className="aura-article-preview mt-5 rounded-xl bg-slate-50 p-6 text-sm leading-7 text-slate-700"><ReactMarkdown>{preview.body}</ReactMarkdown></div></details>
  </>;
}
