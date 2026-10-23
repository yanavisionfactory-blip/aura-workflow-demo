import {useEffect,useRef,useState} from 'react';
import {X,Sparkles,Pencil,ArrowRight,Undo2} from 'lucide-react';
import {editableCopy,simulateEdit} from './contentEdits.mjs';

export function PagePreview({page,compact=false}) {
 return <article className={'rounded-xl bg-[#f8f7f2] p-6 text-[#1c3343] sm:p-8 '+(compact?'':'shadow-lg')}>
  <p className="text-[10px] font-semibold uppercase tracking-[.18em] text-slate-500">Kastner Hill Learning · proposed copy</p>
  <h2 className="mt-5 text-2xl font-semibold leading-tight sm:text-3xl">{page.h1}</h2>
  {(compact?page.sections.slice(0,1):page.sections).map((s,i)=><section key={i} className="mt-6"><h3 className="text-base font-semibold">{s.heading}</h3><p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-slate-600">{s.body}</p></section>)}
  <span className="mt-6 inline-block rounded-lg bg-[#274b5d] px-5 py-3 text-sm font-medium text-white">{page.cta_label}</span>
  <p className="mt-4 text-[11px] text-slate-500">Content preview · layout is illustrative · approval pending</p>
 </article>;
}
export default function ContentEditor({page,mode:initialMode='ai',onSave,onClose,showRevision=false}) {
 const [mode,setMode]=useState(initialMode);
 const [copy,setCopy]=useState(()=>showRevision?simulateEdit(page,'Make it shorter and clearer'):editableCopy(page));
 const [prompt,setPrompt]=useState(showRevision?'Make it shorter and clearer':'');
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const panel=useRef(null);const timer=useRef(null);
 useEffect(()=>{const previous=document.activeElement;panel.current?.querySelector('textarea,input,button')?.focus();return()=>{window.clearTimeout(timer.current);previous?.focus?.();};},[]);
 const update=(key,value)=>{setCopy(c=>({...c,[key]:value}));setError('');};
 const generate=()=>{setError('');setBusy(true);timer.current=window.setTimeout(()=>{try{setCopy(simulateEdit({...page,...copy},prompt));}catch(e){setError(e.message);}finally{setBusy(false);}},500);};
 const changed=JSON.stringify(copy)!==JSON.stringify(editableCopy(page));
 const keys=e=>{if(e.key==='Escape'){e.preventDefault();onClose();}if(e.key==='Tab'){const all=[...panel.current.querySelectorAll('button:not(:disabled),textarea,input,a[href]')];const first=all[0],last=all.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}};
 return <div className="fixed inset-0 z-[60] flex items-start justify-center overflow-auto bg-black/75 p-3 pt-5 backdrop-blur-sm" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}>
 <section ref={panel} onKeyDown={keys} role="dialog" aria-modal="true" aria-labelledby="content-editor-heading" className={'flex '+(showRevision?'max-h-[74vh] ':'max-h-[92vh] ')+'w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-white/15 bg-[#101927] text-slate-100 shadow-2xl'}>
 <header className="flex items-center justify-between border-b border-white/10 p-5"><div><p className="text-[10px] font-semibold uppercase tracking-widest text-violet-300">Local demonstration · unpublished draft</p><h2 id="content-editor-heading" className="mt-1 text-xl font-semibold">Refine your page</h2></div><button type="button" aria-label="Close editor" onClick={onClose} className="rounded-lg p-2 hover:bg-white/10"><X className="h-5 w-5"/></button></header>
 <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[.8fr_1.2fr]">
 <div className="space-y-5 border-r border-white/10 p-5">
 <div className="flex gap-2 rounded-xl bg-black/20 p-1">{[['ai','Ask AURA',Sparkles],['manual','Edit manually',Pencil]].map(([id,label,Icon])=><button type="button" key={id} onClick={()=>setMode(id)} className={'flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-xs '+(mode===id?'bg-violet-500/25 text-violet-200':'text-slate-400')}><Icon className="h-4 w-4"/>{label}</button>)}</div>
 {mode==='ai'?<div><label className="text-sm font-medium" htmlFor="content-edit-prompt">What would you like to change?</label><textarea id="content-edit-prompt" rows={4} value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="Make the introduction shorter and clearer" className="mt-3 w-full rounded-xl border border-white/15 bg-[#0b1320] p-3 text-sm outline-none focus:border-violet-400"/>
 <div className="mt-3 flex flex-wrap gap-2">{['Make it shorter and clearer','Make it warmer for parents','Make the button clearer'].map(text=><button key={text} type="button" onClick={()=>setPrompt(text)} className="rounded-full border border-white/15 px-3 py-2 text-[11px] text-slate-300 hover:border-violet-400">{text}</button>)}</div>
 <button type="button" disabled={busy||!prompt.trim()} onClick={generate} className="mt-5 flex items-center gap-2 rounded-lg bg-violet-500 px-4 py-3 text-sm font-semibold disabled:opacity-40"><Sparkles className="h-4 w-4"/>{busy?'Preparing revision…':'Generate simulated revision'}</button>
 <p className="mt-4 text-xs leading-6 text-slate-400">This demo uses prepared editing rules. No AI service is called. Review the revision before saving it.</p></div>:<div className="space-y-4">
 {['h1','cta_label','page_title','meta_description'].map((key,i)=><label key={key} className="block text-xs text-slate-300">{['Page heading','Button label','Search title','Search description'][i]}<textarea aria-label={['Page heading','Button label','Search title','Search description'][i]} rows={key==='meta_description'?3:2} value={copy[key]} onChange={e=>update(key,e.target.value)} className="mt-2 w-full rounded-lg border border-white/15 bg-[#0b1320] p-3 text-sm"/></label>)}
 {copy.sections.map((section,i)=><div key={i} className="space-y-2 rounded-xl border border-white/10 p-3"><label className="block text-xs">Section {i+1} heading<input aria-label={'Section '+(i+1)+' heading'} value={section.heading} onChange={e=>update('sections',copy.sections.map((s,j)=>j===i?{...s,heading:e.target.value}:s))} className="mt-2 w-full rounded-lg border border-white/15 bg-[#0b1320] p-3 text-sm"/></label><label className="block text-xs">Paragraph<textarea aria-label={'Section '+(i+1)+' paragraph'} rows={5} value={section.body} onChange={e=>update('sections',copy.sections.map((s,j)=>j===i?{...s,body:e.target.value}:s))} className="mt-2 w-full rounded-lg border border-white/15 bg-[#0b1320] p-3 text-sm"/></label></div>)}
 </div>}
 {error&&<p role="alert" className="text-xs leading-6 text-amber-200">{error}</p>}
 </div>
 <div className="space-y-4 bg-[#0b1220] p-5"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold">{changed?'After · proposed revision':'Page preview'}</h3><span className="text-[10px] text-amber-200">Approval pending</span></div>
 {changed&&<details className="rounded-lg border border-white/10 p-3"><summary className="cursor-pointer text-xs text-slate-300">Before · current draft</summary><div className="mt-3"><PagePreview page={page} compact/></div></details>}
 <PagePreview page={{...page,...copy}}/>
 <div className="rounded-xl border border-white/10 p-4"><p className="text-xs text-slate-400">Search preview</p><p className="mt-2 text-lg text-sky-300">{copy.page_title}</p><p className="mt-2 text-xs leading-6 text-slate-300">{copy.meta_description}</p></div></div></div>
 <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 p-4"><button type="button" onClick={()=>{setCopy(editableCopy(page));setError('');}} disabled={!changed||busy} className="flex items-center gap-2 text-xs text-slate-300 disabled:opacity-40"><Undo2 className="h-4 w-4"/>Undo revision</button><div className="flex gap-3"><button type="button" onClick={onClose} className="rounded-lg border border-white/15 px-4 py-2 text-xs">Cancel</button><button type="button" disabled={!changed||busy} onClick={()=>{try{onSave(page.page_id,copy);}catch(e){setError(e.message);}}} className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-xs font-semibold text-[#062b20] disabled:opacity-40">Save demo draft<ArrowRight className="h-4 w-4"/></button></div></footer>
 </section></div>;
}
