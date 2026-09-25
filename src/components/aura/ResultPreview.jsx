import { useState } from "react";
import { ChevronLeft, ChevronRight, MailCheck, Presentation } from "lucide-react";
import BreakdownTable from "./BreakdownTable";

const readableDetail = (value = "") => String(value)
  .split(/\n/)
  .map((line) => line.trim())
  .filter((line) => line && !/(?:https?:\/\/|\b(?:design id|edit url|view url|file id)\s*:|\{\{[^}]+\}\})/i.test(line))
  .join("\n");

function PresentationPreview({ presentation, thumbnailUrl }) {
  const [slideIndex, setSlideIndex] = useState(0);
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  const slides = presentation.slides;
  const slide = slides[Math.min(slideIndex, slides.length - 1)];
  const timeline = presentation.layout === "timeline";
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0b1422]">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3 text-xs text-[#b7c7d9]">
        <span className="flex items-center gap-2"><Presentation className="h-4 w-4 text-[#64dbc4]" /> {thumbnailUrl && !thumbnailFailed && slideIndex === 0 ? "Canva design" : "Created slide content"}</span>
        <span>{timeline ? "Overview" : `${slideIndex + 1} of ${slides.length}`}</span>
      </div>
      {thumbnailUrl && !thumbnailFailed && slideIndex === 0 && <img src={thumbnailUrl} alt={`Finished Canva slide: ${presentation.title}`} onError={() => setThumbnailFailed(true)} className="block aspect-video w-full bg-[#101c2c] object-contain" />}
      {(!thumbnailUrl || thumbnailFailed || slideIndex !== 0) && <div className="relative flex aspect-video min-h-[230px] flex-col justify-center overflow-hidden bg-[#101c2c] px-[7%] py-[5%] text-white sm:min-h-[350px]">
        {timeline ? (
          <>
            <h4 className="text-xl font-bold sm:text-3xl">{presentation.title}</h4>
            {presentation.subtitle && <p className="mt-2 text-sm text-[#b7c7d9]">{presentation.subtitle}</p>}
            <div className="mt-7 grid gap-4" style={{ gridTemplateColumns: `repeat(${Math.min(slides.length, 4)}, minmax(0, 1fr))` }}>
              {slides.map((phase, index) => (
                <div key={index} className="min-w-0 border-t border-[#64dbc4]/60 pt-3">
                  <p className="text-xs font-semibold text-[#64dbc4]">{phase.period}</p>
                  <h5 className="mt-2 text-sm font-semibold sm:text-lg">{phase.title}</h5>
                  <ul className="mt-2 space-y-1 text-[11px] text-[#dce6f1] sm:text-sm">
                    {phase.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          </>
        ) : (
          <>
            <p className="mb-auto text-xs font-medium text-[#b7c7d9] sm:text-sm">{presentation.title}</p>
            <div className="my-auto py-4">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#64dbc4]">{slide.period}</p>
              <h4 className="mt-3 text-2xl font-bold leading-tight sm:text-4xl">{slide.title}</h4>
              <ul className="mt-5 space-y-2 text-sm text-[#dce6f1] sm:text-lg">
                {slide.items.map((item, index) => <li key={index} className="flex gap-2"><span aria-hidden="true">•</span>{item}</li>)}
              </ul>
            </div>
            <div className="mt-auto flex justify-between gap-3 text-[11px] text-[#8295aa]">
              <span>{presentation.subtitle}</span><span className="text-[#64dbc4]">{slideIndex + 1} / {slides.length}</span>
            </div>
          </>
        )}
      </div>}
      {!timeline && slides.length > 1 && (
        <div className="flex items-center justify-center gap-3 border-t border-white/10 p-3">
          <button type="button" onClick={() => setSlideIndex((index) => Math.max(index - 1, 0))} disabled={slideIndex === 0} aria-label="Previous slide" className="rounded-lg p-2 hover:bg-white/10 disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button>
          <span className="text-xs text-muted-foreground">Slide {slideIndex + 1} of {slides.length}</span>
          <button type="button" onClick={() => setSlideIndex((index) => Math.min(index + 1, slides.length - 1))} disabled={slideIndex === slides.length - 1} aria-label="Next slide" className="rounded-lg p-2 hover:bg-white/10 disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
        </div>
      )}
    </div>
  );
}

function ThumbnailOnly({ result }) {
  const [failed, setFailed] = useState(false);
  return !failed
    ? <img src={result.thumbnailUrl} onError={() => setFailed(true)} alt={`Finished Canva design: ${result.title}`} className="block w-full rounded-2xl border border-white/10 bg-[#101c2c] object-contain" />
    : <div className="flex min-h-44 items-center justify-center rounded-2xl border border-white/10 bg-[#101c2c] px-6 text-center text-sm text-[#b7c7d9]">Your presentation is ready. Open it in Canva to see the finished design.</div>;
}

export default function ResultPreview({ result, results }) {
  if (result.kind === "presentation") {
    return result.preview
      ? <PresentationPreview presentation={result.preview} thumbnailUrl={result.thumbnailUrl} />
      : result.thumbnailUrl
        ? <ThumbnailOnly result={result} />
        : <div className="flex min-h-44 items-center justify-center rounded-2xl border border-white/10 bg-[#101c2c] px-6 text-center text-sm text-[#b7c7d9]">Your presentation is ready. Open it in Canva to see the finished design.</div>;
  }
  if (result.kind === "email") {
    return (
      <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0c1422]">
        <div className="flex items-center gap-2 border-b border-white/10 px-5 py-4 text-sm font-semibold"><MailCheck className="h-4 w-4 text-emerald-400" /> Sent email</div>
        <div className="space-y-3 px-5 py-5 text-sm">
          {result.recipient && <p><span className="mr-3 text-muted-foreground">To</span>{result.recipient}</p>}
          {result.subject && <p><span className="mr-3 text-muted-foreground">Subject</span>{result.subject}</p>}
          <div className="whitespace-pre-wrap border-t border-white/10 pt-4 leading-relaxed text-foreground/85">{result.body || readableDetail(result.detail) || results.summary}</div>
        </div>
      </div>
    );
  }
  if (result.kind === "document" && result.preview) return (
    <div className="mx-auto max-w-3xl rounded-2xl border border-white/10 bg-[#f8fafc] px-6 py-8 text-[#1e293b] shadow-lg sm:px-12 sm:py-12">
      <h4 className="mb-6 text-2xl font-semibold">{result.preview.title}</h4>
      <div className="whitespace-pre-wrap text-sm leading-7">{result.preview.body}</div>
    </div>
  );
  if (results.breakdown) return <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0c1422]"><BreakdownTable breakdown={results.breakdown} /></div>;
  if (result.items?.length) return (
    <div className="grid gap-3 sm:grid-cols-2">{result.items.map((item, index) => (
      <div key={index} className="rounded-xl border border-white/10 bg-[#0c1422] p-4">
        <p className="font-medium">{item.label}</p>{item.detail && <p className="mt-2 text-sm text-muted-foreground">{readableDetail(item.detail)}</p>}
      </div>
    ))}</div>
  );
  return <p className="whitespace-pre-wrap rounded-2xl border border-white/10 bg-[#0c1422] p-5 text-sm leading-relaxed text-foreground/85">{readableDetail(result.detail) || results.summary || "Your result is ready in the connected app."}</p>;
}
