const steps=[
 {name:'Create Salesforce account',detail:'Account details and approved contract value',system:'SF'},
 {name:'Create Stripe customer',detail:'Link Stripe customer ID back to Salesforce',system:'ST'},
 {name:'Create Google Drive workspace',detail:'Apply the approved internal permission group',system:'GD'},
 {name:'Announce readiness in Slack',detail:'Unlocked only after every system is verified',system:'SL'}
];
const timeline=document.querySelector('#timeline');
const execution=document.querySelector('#executionSection');
const recovery=document.querySelector('#recoveryPanel');
const certificate=document.querySelector('#certificate');
const approve=document.querySelector('#approveBtn');
const runStatus=document.querySelector('#runStatus');
const contractStatus=document.querySelector('#contractStatus');
let timers=[];

function render(states=['pending','pending','pending','locked']){
 timeline.innerHTML=steps.map((s,i)=>`<div class="step ${states[i]}"><span class="step-icon">${states[i]==='complete'?'✓':states[i]==='failed'?'!':i+1}</span><div><strong>${s.name}</strong><small>${s.detail}</small></div><span class="step-state">${({pending:'PENDING',active:'IN PROGRESS',complete:'VERIFIED',failed:'FAILED SAFELY',locked:'LOCKED'})[states[i]]}</span></div>`).join('');
}
function later(fn,ms){timers.push(setTimeout(fn,ms))}
function start(){
 approve.disabled=true; approve.textContent='Running…'; contractStatus.textContent='Approved by Yana'; contractStatus.className='status-pill success';
 execution.classList.remove('hidden'); certificate.classList.add('hidden'); recovery.classList.add('hidden'); render(['active','pending','pending','locked']); execution.scrollIntoView({behavior:'smooth',block:'start'});
 later(()=>render(['complete','active','pending','locked']),900);
 later(()=>render(['complete','complete','active','locked']),1800);
 later(()=>{render(['complete','complete','failed','locked']);runStatus.innerHTML='Paused safely';runStatus.className='status-pill neutral';recovery.classList.remove('hidden')},2900);
}
function recover(){
 document.querySelector('#recoverBtn').disabled=true;document.querySelector('#recoverBtn').textContent='Recovering…';runStatus.innerHTML='<i></i> Recovering';runStatus.className='status-pill running';recovery.classList.add('hidden');render(['complete','complete','active','locked']);
 later(()=>render(['complete','complete','complete','active']),1100);
 later(()=>{render(['complete','complete','complete','complete']);runStatus.textContent='Verified';runStatus.className='status-pill success';document.querySelector('#executionTitle').textContent='Outcome verified';document.querySelector('#executionSub').textContent='AURA re-read every affected system before calling the workflow complete.';certificate.classList.remove('hidden');certificate.scrollIntoView({behavior:'smooth',block:'start'})},2100);
}
function reset(){timers.forEach(clearTimeout);timers=[];execution.classList.add('hidden');certificate.classList.add('hidden');recovery.classList.add('hidden');approve.disabled=false;approve.innerHTML='Approve & run workflow <span>→</span>';contractStatus.textContent='Ready for approval';contractStatus.className='status-pill neutral';runStatus.innerHTML='<i></i> Running';runStatus.className='status-pill running';document.querySelector('#recoverBtn').disabled=false;document.querySelector('#recoverBtn').innerHTML='Approve recovery <span>→</span>';document.querySelector('#executionTitle').textContent='Making the outcome true';document.querySelector('#executionSub').textContent='AURA is checking each action before unlocking the next.';document.querySelector('#contractSection').scrollIntoView({behavior:'smooth',block:'center'})}
approve.addEventListener('click',start);document.querySelector('#recoverBtn').addEventListener('click',recover);document.querySelector('#resetBtn').addEventListener('click',reset);
const dialog=document.querySelector('#evidenceDialog');document.querySelector('#evidenceBtn').addEventListener('click',()=>dialog.showModal());document.querySelector('#closeDialog').addEventListener('click',()=>dialog.close());
render();
