import {useState} from 'react';
import {Sparkles,Pencil,X} from 'lucide-react';
import {draftText,editDraft,localRevision} from './model.mjs';
import ToolScreen from './ToolScreen';
import Measurement from './Measurement';
import {toolNames} from './data.mjs';
export default function Editor({draft,state,mode,onSave,onClose}){
 const [tab,setTab]=useState(mode),[text,setText]=useState(draftText(draft,state)),[instruction,setInstruction]=useState('Make this shorter and keep the next step clear.'),[revision,setRevision]=useState(null),[error,setError]=useState('');
 const working=tab==='ai'?(revision??text):text;
 let previewState=state;try{previewState=editDraft(state,draft.id,working);}catch{/* Keep the last valid screen when a field is blank. */}
 const tool=draft.channel==='hubspot'&&state.crm==='aura'?'tracker':draft.channel,noop=()=>{};
 return <div className="ec-modal-backdrop" role="presentation"><section className="ec-edit-modal ec-screen-editor" role="dialog" aria-modal="true" aria-label="Edit content draft">
  <header><div><p className="ec-eyebrow">{toolNames[tool]} · draft editing</p><h2>{draft.label}</h2></div><button aria-label="Close editor" onClick={onClose}><X size={18}/></button></header>
  <div className="ec-editor-layout"><div className="ec-editor-fields">
   <div className="ec-edit-tabs"><button className={tab==='ai'?'active':''} onClick={()=>setTab('ai')}><Sparkles size={14}/>Ask AURA</button><button className={tab==='manual'?'active':''} onClick={()=>{if(revision!==null)setText(revision);setTab('manual');}}><Pencil size={14}/>Edit manually</button></div>
   {tab==='ai'?<><label>Your instruction<textarea aria-label="Your instruction" rows={3} value={instruction} onChange={e=>setInstruction(e.target.value)}/></label><button className="ec-purple-button" disabled={!instruction.trim()} onClick={()=>setRevision(localRevision(text,instruction))}>Generate demo revision</button><small>Prepared editing rules simulate AI. No model or provider is called.</small><label className="mt-4">{revision!==null?'Proposed revision':'Current draft'}<textarea aria-label="Proposed revision" rows={10} value={revision??text} onChange={e=>setRevision(e.target.value)}/></label></>:<label>Draft text<textarea aria-label="Draft text" rows={15} value={text} onChange={e=>setText(e.target.value)}/></label>}
   {error&&<p role="alert">{error}</p>}
  </div><div className="ec-editor-preview"><h3>Screen preview</h3><p>Updates as you edit. Save to apply it to the walkthrough and tool.</p><div role="region" aria-label="Live screen preview" tabIndex={0} data-edit-target={draft.nextAction?'next-action':draft.channel} className={'ea-editor-tool-frame '+(tool==='measurement'?'ea-report-frame':'')}>
   <div inert="">{tool==='measurement'?<Measurement state={previewState} update={noop} preview/>:<ToolScreen id={tool} state={previewState} update={noop} notify={noop} onEdit={noop} embedded preview fixedPostId={draft.source?draft.id:undefined} fixedRecordId={draft.recordId} fixedKind={draft.kind} initialView={draft.view||'content'}/>}</div>
  </div></div></div>
  <footer><p>Saving updates this draft and clears its earlier approval. Changes stay in this browser.</p><button onClick={onClose}>Cancel</button><button className="ec-purple-button" disabled={!working.trim()||(tab==='ai'&&revision===null)} onClick={()=>{try{if(working.length>6000)throw Error('Use up to 6,000 characters.');onSave(draft.id,working);}catch(e){setError(e.message);}}}>Save changes</button></footer>
 </section></div>;
}
