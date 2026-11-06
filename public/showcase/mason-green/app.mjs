import { rows, retryPrompt, originalSheet } from './data.mjs';

const views = {
  kpis: { title: 'KPI dashboard · September 2026', description: 'Four core metrics, with targets separated from actual business performance.', header: 1, indices: [2,3,4,5], widths: [18,9,17,9,13,34], note: 'Actual company performance was not found in the public evidence. The conversion and order-value targets are proposed industry benchmarks; blanks do not mean zero.' },
  comparison: { title: 'Company comparison', description: 'The product facts AURA recorded for the three named brands. Prices reflect retrieval time, not verified September prices.', header: 16, indices: [17,18,19,20,21], columns: 4, widths: [25,25,25,25], note: 'The attempted Dermalogica source was blocked. Product sizes were not established, so these are listed prices, not a price-per-volume comparison.' },
  benchmarks: { title: 'Benchmarks and an illustrative scenario', description: 'Industry evidence and a calculation, kept separate from Plantéa’s actual performance.', indices: [7,8,9,11,12,13,14], widths: [24,9,20,18,15,14], note: 'Scenario only: 1,000 visits × 2.6% = 26 orders; 26 × $70 = $1,820. This is not a traffic estimate or an observed revenue result. The benchmark period is 3 Aug–31 Oct 2026.' },
  all: { title: 'All saved rows · Dashboard', description: 'The 37 rows read back from the saved workbook, with original row numbers and cell text. The write covered A–G; this read-back contains A–F.', indices: rows.map((_,i)=>i), rowNumbers: true, widths: [19,15,16,16,14,20], note: 'This is the recorded preview, not a live connection to Google Sheets. The saved run still needs final review.' },
};

export function auraUrl(prompt, currentUrl) {
  const url = new URL('../../', currentUrl);
  url.searchParams.set('prompt', prompt.trim());
  return url.href;
}

export function mountDemo(document) {
  const win = document.defaultView;
  const panel = document.getElementById('sheet-panel');
  const table = document.getElementById('result-table');
  const tabs = [...document.querySelectorAll('[data-view]')];
  const make = (tag, text, className) => { const el=document.createElement(tag); if(text!==undefined)el.textContent=text; if(className)el.className=className;return el; };
  function showView(key, focus=false) {
    const view=views[key]; if(!view)return;
    tabs.forEach(tab=>{ const selected=tab.dataset.view===key;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;if(selected&&focus)tab.focus(); });
    panel.setAttribute('aria-labelledby',`tab-${key}`);
    document.getElementById('view-title').textContent=view.title;
    document.getElementById('view-description').textContent=view.description;
    document.getElementById('view-note').textContent=view.note;
    table.replaceChildren();
    const count=view.columns||6, cols=make('colgroup');
    if(view.rowNumbers){const col=make('col');col.className='row-index';cols.append(col);}
    view.widths.forEach(width=>{const col=make('col');col.setAttribute('width',width+'%');cols.append(col);});table.append(cols);
    const head=make('thead'),headRow=make('tr');
    if(view.rowNumbers)headRow.append(make('th','', 'row-index'));
    const headers=view.header!==undefined?rows[view.header].slice(0,count):['A','B','C','D','E','F'];
    headers.forEach(text=>{const th=make('th',text);th.scope='col';headRow.append(th);});head.append(headRow);table.append(head);
    const body=make('tbody');
    view.indices.forEach(index=>{
      const tr=make('tr');if(view.rowNumbers)tr.append(make('td',String(index+1),'row-index'));
      rows[index].slice(0,count).forEach((raw,column)=>{
        let value=raw;if(key==='kpis'&&index===4&&column===1)value='2.6%';if(key==='kpis'&&index===5&&column===1)value='$70';
        const td=make('td');
        if(!value)td.append(make('span',view.rowNumbers?'':'—','cell-empty'));
        else if(/^https:\/\//.test(value)){const a=make('a',new URL(value).hostname.replace(/^www\./,''),'result-link');a.href=value;a.target='_blank';a.rel='noopener noreferrer';td.append(a);if(view.rowNumbers)a.textContent=value;}
        else if(value==='Awaiting input'){td.className='cell-status';td.append(make('span',value));}
        else {td.textContent=value;if(value==='Not publicly reported')td.className='cell-unavailable';}
        tr.append(td);
      });body.append(tr);
    });table.append(body);
    table.closest('.table-scroll').scrollTop=0;table.closest('.table-scroll').scrollLeft=0;
  }
  tabs.forEach((tab,index)=>{tab.addEventListener('click',()=>showView(tab.dataset.view));tab.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(index+1)%tabs.length;if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;if(next!==undefined){event.preventDefault();showView(tabs[next].dataset.view,true);}});});
  showView('kpis');
  document.getElementById('original-sheet').href=originalSheet;
  const prompt=document.getElementById('retry-prompt'),tryLink=document.getElementById('try-aura'),promptStatus=document.getElementById('prompt-status');
  prompt.value=retryPrompt;
  function syncPrompt(){const valid=Boolean(prompt.value.trim())&&prompt.value.length<=20000;if(valid){tryLink.href=auraUrl(prompt.value,win.location.href);tryLink.removeAttribute('aria-disabled');}else{tryLink.removeAttribute('href');tryLink.setAttribute('aria-disabled','true');}return valid;}
  prompt.addEventListener('input',()=>{promptStatus.textContent=syncPrompt()?'Your edited prompt will open in AURA for review.':'Enter a prompt of up to 20,000 characters before opening AURA.';});syncPrompt();
  tryLink.addEventListener('click',event=>{if(!syncPrompt())event.preventDefault();});
  async function copy(text,target,ok,fallback){try{if(!win.navigator.clipboard?.writeText)throw Error('Clipboard unavailable');await win.navigator.clipboard.writeText(text);target.textContent=ok;}catch{target.textContent=fallback;}}
  document.getElementById('copy-prompt').addEventListener('click',async()=>{if(!syncPrompt()){prompt.focus();return;}await copy(prompt.value,promptStatus,'Prompt copied. Paste it into AURA’s prompt box.','Clipboard access is unavailable here. Select and copy the prompt above.');});
  document.getElementById('restore-prompt').addEventListener('click',()=>{prompt.value=retryPrompt;syncPrompt();promptStatus.textContent='Original retry prompt restored.';});
  const feedback=document.getElementById('feedback'),feedbackStatus=document.getElementById('feedback-status');
  document.getElementById('copy-feedback').addEventListener('click',async()=>{if(!feedback.value.trim()){feedbackStatus.textContent='Write your feedback first.';feedback.focus();return;}await copy('Mason’s AURA repeat test — Plantéa\n\n'+feedback.value.trim(),feedbackStatus,'Feedback copied. Send it back to Yana when you’re ready.','Select and copy your feedback. Nothing was submitted.');});
  const dialog=document.getElementById('screen-dialog');document.getElementById('show-screen').addEventListener('click',()=>dialog.showModal());document.getElementById('close-screen').addEventListener('click',()=>dialog.close());dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  return {showView};
}
if(typeof document!=='undefined')mountDemo(document);
