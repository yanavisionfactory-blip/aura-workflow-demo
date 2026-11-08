import {originalSheet,retryPrompt,views,stages,slideTitles} from './data.mjs';

export function auraUrl(prompt,currentUrl){
  const url=new URL('../../',currentUrl);
  url.searchParams.set('prompt',prompt.trim());
  return url.href;
}

export function mountDemo(document){
  const win=document.defaultView;
  const byId=id=>document.getElementById(id);
  const make=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
  const tabs=[...document.querySelectorAll('[data-view]')];
  function showView(key,focus=false){
    const view=views[key];if(!view)return;
    tabs.forEach(tab=>{const selected=tab.dataset.view===key;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;if(selected&&focus)tab.focus();});
    byId('sheet-panel').setAttribute('aria-labelledby','tab-'+key);
    byId('view-title').textContent=view.title;byId('view-description').textContent=view.description;byId('view-note').textContent=view.note;
    const table=byId('result-table');table.replaceChildren();table.dataset.view=key;
    const cols=make('colgroup');view.widths.forEach(width=>{const col=make('col');col.setAttribute('width',width+'%');cols.append(col);});table.append(cols);
    const head=make('thead'),headRow=make('tr');view.headers.forEach(text=>{const th=make('th',text);th.scope='col';headRow.append(th);});head.append(headRow);table.append(head);
    const body=make('tbody');view.rows.forEach(row=>{const tr=make('tr');row.forEach(text=>tr.append(make('td',text)));body.append(tr);});table.append(body);
    table.closest('.table-scroll').scrollTop=0;table.closest('.table-scroll').scrollLeft=0;
  }
  function bindTabs(elements,select,key){elements.forEach((tab,index)=>{tab.addEventListener('click',()=>select(tab.dataset[key]));tab.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(index+1)%elements.length;if(event.key==='ArrowLeft')next=(index+elements.length-1)%elements.length;if(event.key==='Home')next=0;if(event.key==='End')next=elements.length-1;if(next!==undefined){event.preventDefault();select(elements[next].dataset[key],true);}});});}
  bindTabs(tabs,showView,'view');showView('summary');byId('original-sheet').href=originalSheet;

  let stageIndex=0;
  const stageTabs=[...document.querySelectorAll('[data-stage]')];
  function showStage(index,focus=false){
    index=Number(index);if(!Number.isInteger(index)||!stages[index])return;stageIndex=index;
    stageTabs.forEach(tab=>{const selected=Number(tab.dataset.stage)===index;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;if(selected&&focus)tab.focus();});
    const stage=stages[index];byId('walkthrough-panel').setAttribute('aria-labelledby','stage-'+index);
    byId('stage-kicker').textContent='SAVED WORKFLOW · '+stage.kind.toUpperCase();byId('stage-title').textContent=stage.title;byId('stage-subtitle').textContent=stage.subtitle;byId('stage-note').textContent=stage.note;
    const content=byId('stage-content');content.replaceChildren();
    if(stage.body)content.append(make('blockquote',stage.body));
    if(stage.steps){const list=make('ol',undefined,'run-steps');stage.steps.forEach(([title,description],i)=>{const item=make('li');item.append(make('span',stage.kind==='plan'?String(i+1):'✓','run-step-number'));const text=make('div');text.append(make('strong',title),make('p',description));item.append(text);list.append(item);});content.append(list);}
    if(stage.kind==='result'){const link=make('a','Inspect the saved outputs ↑','button primary run-result-link');link.href='#result';content.append(link);}
    byId('stage-count').textContent=`${index+1} / ${stages.length}`;
    byId('previous-stage').disabled=index===0;byId('next-stage').textContent=index===stages.length-1?'View saved results ↑':'Next step →';
  }
  bindTabs(stageTabs,showStage,'stage');showStage(0);
  byId('previous-stage').addEventListener('click',()=>showStage(stageIndex-1));
  byId('next-stage').addEventListener('click',()=>{if(stageIndex===stages.length-1){win.location.hash='result';byId('result-title').focus();}else showStage(stageIndex+1);});
  byId('restart-walkthrough').addEventListener('click',()=>showStage(0,true));

  let slideIndex=0;
  function showSlide(index){slideIndex=(index+slideTitles.length)%slideTitles.length;const title=slideTitles[slideIndex];for(const id of ['slide-image','expanded-slide']){byId(id).src=`./slide-${slideIndex+1}.png`;byId(id).alt=`Saved presentation slide ${slideIndex+1}: ${title}`;}byId('slide-label').textContent=`${slideIndex+1} / ${slideTitles.length} · ${title}`;byId('slide-dialog-title').textContent=title;}
  byId('previous-slide').addEventListener('click',()=>showSlide(slideIndex-1));byId('next-slide').addEventListener('click',()=>showSlide(slideIndex+1));
  function bindDialog(dialogId,openId,closeId){const dialog=byId(dialogId);byId(openId).addEventListener('click',()=>dialog.showModal());byId(closeId).addEventListener('click',()=>dialog.close());dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});}
  bindDialog('screen-dialog','show-screen','close-screen');bindDialog('slide-dialog','expand-slide','close-slide');showSlide(0);

  const prompt=byId('retry-prompt'),tryLink=byId('try-aura'),promptStatus=byId('prompt-status');prompt.value=retryPrompt;
  function syncPrompt(){const valid=Boolean(prompt.value.trim())&&prompt.value.length<=20000;if(valid){tryLink.href=auraUrl(prompt.value,win.location.href);tryLink.removeAttribute('aria-disabled');}else{tryLink.removeAttribute('href');tryLink.setAttribute('aria-disabled','true');}return valid;}
  prompt.addEventListener('input',()=>{promptStatus.textContent=syncPrompt()?'Your edited prompt will open in AURA for review.':'Enter a prompt of up to 20,000 characters before opening AURA.';});syncPrompt();
  tryLink.addEventListener('click',event=>{if(!syncPrompt())event.preventDefault();});
  byId('copy-prompt').addEventListener('click',async()=>{if(!syncPrompt()){prompt.focus();return;}try{if(!win.navigator.clipboard?.writeText)throw Error('Clipboard unavailable');await win.navigator.clipboard.writeText(prompt.value);promptStatus.textContent='Prompt copied. Paste it into AURA’s prompt box.';}catch{promptStatus.textContent='Clipboard access is unavailable here. Select and copy the prompt above.';}});
  byId('restore-prompt').addEventListener('click',()=>{prompt.value=retryPrompt;syncPrompt();promptStatus.textContent='Original prompt restored.';});
  return {showView,showStage,showSlide};
}
if(typeof document!=='undefined')mountDemo(document);
