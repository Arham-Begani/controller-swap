const $ = id => document.getElementById(id);
const modeNames = {human_steps:'Human steps',standing_instruction:'Standing instruction',ai_steps:'AI steps'};
const viewNames = {actions:'Outward activity',messages:'Activity + messages',complete:'Complete records'};
let token = '', tasks = [], runs = [], current = null, currentEvidence = null, busy = false;
let noticeTimer;
const systemMotion = matchMedia('(prefers-reduced-motion: reduce)');
let motionPreference = 'on', traceTimer;
try { motionPreference = localStorage.getItem('cs-motion') || 'on'; } catch {}
const motionEnabled = () => !systemMotion.matches && motionPreference !== 'off';
function updateMotion() {
  const enabled = motionEnabled();
  document.documentElement.dataset.motion = enabled ? 'on' : 'off';
  $('motion-toggle').setAttribute('aria-pressed', String(enabled));
  $('motion-toggle').textContent = enabled ? 'Motion on' : 'Motion off';
  $('motion-toggle').setAttribute('aria-label', systemMotion.matches ? 'Motion off: device reduced-motion preference' : 'Enable interface motion');
  $('replay-trace').setAttribute('aria-disabled', String(!enabled));
  if (!enabled) {
    clearTimeout(traceTimer);
    $('trace-figure').classList.remove('motion-playing');
    document.getAnimations().forEach(animation => animation.cancel());
  }
}
function reveal(node, distance=12) {
  if (!motionEnabled() || !node || node.hidden) return;
  node.getAnimations().forEach(animation => animation.cancel());
  node.animate([{opacity:.25,transform:`translateY(${distance}px)`},{opacity:1,transform:'translateY(0)'}],{duration:420,easing:'cubic-bezier(.2,.75,.2,1)'});
}
function playTrace() {
  if (!motionEnabled()) return;
  const figure = $('trace-figure');
  clearTimeout(traceTimer);
  figure.classList.remove('motion-playing');
  void figure.offsetWidth;
  figure.classList.add('motion-playing');
  traceTimer = setTimeout(() => figure.classList.remove('motion-playing'), 3300);
}
$('motion-toggle').addEventListener('click', () => {
  if(systemMotion.matches) { notice('Motion is off to respect your device reduced-motion setting.'); return; }
  motionPreference = motionEnabled() ? 'off' : 'on';
  try { localStorage.setItem('cs-motion', motionPreference); } catch {}
  updateMotion();
  if(motionEnabled() && !$('overview').hidden) playTrace();
});
systemMotion.addEventListener('change', updateMotion);
$('replay-trace').addEventListener('click', playTrace);
updateMotion();
const traceObserver = new IntersectionObserver(entries => {
  if(entries.some(entry => entry.isIntersecting)) { playTrace(); traceObserver.disconnect(); }
}, {threshold:.4});
traceObserver.observe($('trace-figure'));

function notice(text, error=false) {
  clearTimeout(noticeTimer);
  const box=$('notice'); box.replaceChildren(el('span',text)); box.classList.toggle('error',error);
  if(error){const dismiss=document.createElement('button');dismiss.type='button';dismiss.textContent='Dismiss';dismiss.addEventListener('click',()=>box.replaceChildren());box.append(dismiss);}
  else noticeTimer=setTimeout(()=>box.replaceChildren(),9000);
}
async function api(path, data) {
  let response;
  try{response=await fetch(path, data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CS-Token':token},body:JSON.stringify(data)});}
  catch{throw new Error('Cannot reach the local workspace. Check that the server is running, then choose Refresh. Your saved records remain on disk.');}
  if(response.headers.get('X-CS-Preview')==='synthetic-only') $('preview-notice').hidden=false;
  const result=await response.json(); if(!response.ok) throw new Error(result.error||'Request failed'); return result;
}
async function action(fn, message='Updating the local workspace…') {
  if(busy)return;busy=true;
  const focused=document.activeElement;
  const previous=new Map();document.querySelectorAll('button,select,input,textarea').forEach(b=>{previous.set(b,b.disabled);b.disabled=true;});
  $('activity').textContent=message;$('activity').hidden=false;$('main').setAttribute('aria-busy','true');
  try{await fn();}catch(e){notice(e.message,true);}
  finally{busy=false;document.querySelectorAll('button,select,input,textarea').forEach(b=>b.disabled=previous.get(b)??false);$('activity').hidden=true;$('main').setAttribute('aria-busy','false');if(focused?.isConnected&&focused.matches('button,select,input,textarea')&&!focused.disabled&&!focused.closest('[hidden]'))focused.focus({preventScroll:true});}
}
function el(tag,text,cls) {const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;if(['button','select','input','textarea'].includes(tag))node.disabled=busy;return node;}
function cell(row,text,cls) {const node=el('td',text,cls);row.append(node);return node;}
function option(select,value,text) {const node=el('option',text);node.value=value;select.append(node);}
const pageNames={overview:'Overview',studio:'Run studio',evidence:'Compare evidence',analysis:'Analysis',protocol:'Protocol & exports'};
function page(focus=false) {const name=Object.hasOwn(pageNames,location.hash.slice(1))?location.hash.slice(1):'overview';document.querySelectorAll('.page').forEach(x=>x.hidden=x.id!==name);document.querySelectorAll('[data-nav]').forEach(x=>{const active=x.dataset.nav===name;x.classList.toggle('active',active);if(active)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');});$('breadcrumb').textContent='Notebook / '+pageNames[name];document.title=pageNames[name]+' — Controller Swap';if(focus){const heading=$(name).querySelector('h1');heading.tabIndex=-1;heading.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}reveal($(name));}
window.addEventListener('hashchange',()=>page(true));
document.querySelector('.skip-link').addEventListener('click',event=>{event.preventDefault();$('main').focus();});
document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>{location.hash=b.dataset.go;}));
function renderStats(s) {$('stats').replaceChildren();for(const [label,value,note] of [['Planned study sessions',72,'Protocol target'],['Demo / fixture sessions',s.fixture_sessions,'Software diagnostics only'],['Verified research runs',s.verified_research_runs,'Requires genuine collection + review'],['Model endpoint calls',s.model.calls,s.model.enabled?'Explicitly enabled':'Disabled by default']]) {const n=el('div',undefined,'stat');n.append(el('span',label),el('strong',String(value)),el('small',note));$('stats').append(n);}$('protocol-hash').textContent=s.protocol_hash;$('connector-status').textContent=s.model.enabled?(s.model.configured?'Configured. Call limit: '+s.model.limit+'.':'Enabled, but no complete model configuration found.'):'Live requests are disabled. The deterministic local backend is available.';$('model-option').disabled=!(s.model.enabled&&s.model.configured);for(const o of $('method').options)if(o.value.startsWith('model_'))o.disabled=!(s.model.enabled&&s.model.configured);}
function renderRuns() {$('matrix').replaceChildren();for(const task of tasks){const row=el('tr');cell(row,task.title);const split=cell(row);split.append(el('span',task.split,'tag'));for(const mode of Object.keys(modeNames)){const n=runs.filter(r=>r.task===task.id&&r.mode===mode&&r.scope==='synthetic_fixture'&&r.status==='complete').length;const value=cell(row,n+' / 4','count');value.dataset.label=mode==='standing_instruction'?'Standing':modeNames[mode];}$('matrix').append(row);}
  renderSessionList();
  const selected=$('evidence-run').value;$('evidence-run').replaceChildren();for(const r of [...runs].reverse())option($('evidence-run'),r.id,sessionLabel(r));if(runs.some(r=>r.id===selected))$('evidence-run').value=selected;renderComparisonChoices();
}
function sessionLabel(r){return (tasks.find(t=>t.id===r.task)?.title||r.task)+' / '+modeNames[r.mode]+' / '+r.worker.replace('worker_','Worker ').toUpperCase()+' / rep '+r.repetition+' / '+r.id.slice(0,8);}
function renderSessionList(){
  const query=$('session-search').value.trim().toLowerCase();
  const matches=[...runs].reverse().filter(r=>(sessionLabel(r)+' '+r.scope+' '+r.status+' '+r.id).toLowerCase().includes(query));
  $('runs').replaceChildren();$('session-count').textContent=query?matches.length+' of '+runs.length+' sessions':runs.length+' stored sessions';
  for(const r of matches){const row=el('tr');const button=el('button',r.id.slice(0,8),'link-button');button.setAttribute('aria-label','Open '+sessionLabel(r));button.addEventListener('click',()=>action(async()=>{current=await api('/api/runs/'+r.id);renderSession();location.hash='studio';$('session').scrollIntoView({block:'start'});}));cell(row).append(button);cell(row,tasks.find(t=>t.id===r.task)?.title||r.task);cell(row,modeNames[r.mode]);cell(row).append(el('span',r.scope.replaceAll('_',' '),'tag demo'));cell(row,r.status);cell(row,r.score.correct+' / '+r.score.total);$('runs').append(row);}
  if(!matches.length){const row=el('tr');cell(row,query?'No matching sessions. Try a task name, arrangement or session ID.':'Your notebook is empty. Create a mock session above, or try the sample comparison.').colSpan=6;$('runs').append(row);}
}
$('session-search').addEventListener('input',renderSessionList);
async function openSampleComparison(){
  const find=mode=>runs.find(r=>r.task==='files'&&r.mode===mode&&r.worker==='worker_a'&&r.repetition===1&&r.scope==='synthetic_fixture'&&r.status==='complete');
  if(!find('human_steps')||!find('ai_steps')){await api('/api/demo',{});await refresh();}
  const left=find('human_steps'),right=find('ai_steps');
  if(!left||!right)throw new Error('The sample pair is unavailable. Refresh the workspace and try again.');
  $('evidence-run').value=left.id;$('evidence-view').value='actions';renderComparisonChoices();$('comparison-run').value=right.id;
  location.hash='evidence';await inspectEvidence();await compareEvidence();
  notice('Synthetic sample pair loaded. No model calls were made. Change the evidence view, then compare again.');
}
document.querySelectorAll('[data-sample]').forEach(button=>button.addEventListener('click',()=>action(openSampleComparison,'Preparing the synthetic sample pair…')));
async function refresh(){const [s,t,r]=await Promise.all([api('/api/status'),api('/api/tasks'),api('/api/runs')]);token=s.token;tasks=t;runs=r;if(!$('task').options.length)for(const task of tasks)option($('task'),task.id,task.title);renderStats(s);renderRuns();await analysis();}
function renderSession(){if(!current)return;const r=current,task=r.task_spec||tasks.find(t=>t.id===r.task);const box=$('session');box.replaceChildren();const head=el('div',undefined,'session-head');head.append(el('h2',task.title),el('span',r.id.slice(0,8),'tag'));box.append(head,el('p',task.rule,'session-rule'),el('p',modeNames[r.mode]+' · '+r.worker+' · '+r.scope.replaceAll('_',' '),'session-progress'));
const records=el('div',undefined,'record-grid');for(const rec of task.records){const done=Object.hasOwn(r.state,rec.id);const n=el('div',undefined,'record'+(done?' done':''));n.append(el('strong',rec.id+(done?' → '+r.state[rec.id]:'')),el('span',JSON.stringify(Object.fromEntries(Object.entries(rec).filter(([k])=>k!=='id')))));records.append(n);}box.append(records);
if(r.status==='complete'){box.append(el('div','Session complete. '+Object.keys(r.state).length+' mock records processed. This session has not been verified as research data.','session-result'));const inspect=el('button','Inspect evidence →','secondary');inspect.addEventListener('click',()=>{$('evidence-run').value=r.id;renderComparisonChoices();location.hash='evidence';action(inspectEvidence);});box.append(inspect);return;}
const remaining=task.records.filter(x=>!Object.hasOwn(r.state,x.id));if(r.mode==='human_steps'){const rowLabel=el('label','Mock record');const rows=el('select');rows.id='decision-record';for(const rec of remaining)option(rows,rec.id,rec.id);rowLabel.append(rows);const valueLabel=el('label','Chosen value');const values=el('select');values.id='decision-value';for(const v of task.values)option(values,v,v);valueLabel.append(values);const textLabel=el('label','Instruction note (optional)');const input=el('textarea');input.id='decision-note';input.maxLength=2000;input.placeholder='Explain your selected update';textLabel.append(input);box.append(rowLabel,valueLabel,textLabel);}
const button=el('button',r.mode==='human_steps'?'Record choice & run worker →':'Advance one mock action →','primary');button.id='advance';button.addEventListener('click',()=>action(async()=>{const data=r.mode==='human_steps'?{action:{record:$('decision-record').value,value:$('decision-value').value},instruction:$('decision-note').value}:{};current=await api('/api/runs/'+r.id+'/step',data);current.task_spec=task;renderSession();await refresh();}));box.append(button);}
async function inspectEvidence(){const id=$('evidence-run').value;if(!id){notice('Create or generate a session first.');return;}currentEvidence=null;
  try{currentEvidence=await api('/api/runs/'+id+'/view?view='+$('evidence-view').value);}
  catch(error){$('trace').replaceChildren(el('div','This record could not be loaded. Check the local server, then choose Inspect record to try again.','card empty'));$('view-warning').replaceChildren(el('strong','Evidence not loaded'),el('span','The previous record has been cleared so it cannot be mistaken for this selection.'));throw error;}
  $('view-warning').replaceChildren(el('strong',viewNames[currentEvidence.view]),el('span',currentEvidence.warning));$('trace').replaceChildren();for(const e of currentEvidence.events){const card=el('article',undefined,'card event');card.append(el('div',e.record_ref,'event-ref'));const body=el('div');const h=el('h3',e.kind.replaceAll('_',' '));if(e.source)h.append(el('span',e.source,'event-source'));body.append(h,el('pre',JSON.stringify(e.data,null,2)));card.append(body);$('trace').append(card);}if(!currentEvidence.events.length)$('trace').append(el('div','No activity is available in this view.','card empty'));}
function renderComparisonChoices(){
  const left=runs.find(r=>r.id===$('evidence-run').value), previous=$('comparison-run').value;
  const candidates=runs.filter(r=>r.id!==left?.id&&r.status==='complete');
  const rank=r=>Number(r.task===left?.task)*8+Number(r.worker===left?.worker)*4+Number(r.repetition===left?.repetition)*2+Number(r.mode!==left?.mode);
  candidates.sort((a,b)=>rank(b)-rank(a));$('comparison-run').replaceChildren();
  for(const r of candidates)option($('comparison-run'),r.id,sessionLabel(r));
  if(candidates.some(r=>r.id===previous))$('comparison-run').value=previous;
  $('comparison-result').hidden=true;
}
function stableJSON(value){if(Array.isArray(value))return '['+value.map(stableJSON).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stableJSON(value[k])).join(',')+'}';return JSON.stringify(value);}
async function compareEvidence(){
  const ids=[$('evidence-run').value,$('comparison-run').value],view=$('evidence-view').value;
  if(!ids[0]||!ids[1]||ids[0]===ids[1])throw new Error('Select two different sessions to compare.');
  const inputs=await Promise.all(ids.map(id=>api('/api/runs/'+id+'/view?view='+view)));
  const same=stableJSON(inputs[0])===stableJSON(inputs[1]);
  const sameRecords=inputs[0].events.filter((event,index)=>stableJSON(event)===stableJSON(inputs[1].events[index])).length;
  const verdict=$('comparison-verdict');verdict.replaceChildren();verdict.classList.toggle('is-identical',same);
  verdict.append(el('span',viewNames[view],'eyebrow'),el('h2',same?'Identical evaluator inputs':'The evaluator inputs differ'),el('p',same?'A deterministic evaluator receiving only these inputs must give the same answer to both. Setup labels can still differ.':'Differences are highlighted below. Different inputs alone do not establish reliable attribution.'),el('small',sameRecords+' matching event positions; '+inputs[0].events.length+' records on the left and '+inputs[1].events.length+' on the right.'));
  $('comparison-panels').replaceChildren();
  inputs.forEach((input,index)=>{
    const run=runs.find(r=>r.id===ids[index]),panel=el('section',undefined,'card comparison-panel');
    panel.setAttribute('aria-label',(index?'Right':'Left')+' evidence comparison');
    const head=el('div',undefined,'comparison-heading');head.append(el('span',index?'SESSION B':'SESSION A','eyebrow'),el('h3',modeNames[run.mode]),el('p','Assigned setup / '+run.worker+' / '+run.scope.replaceAll('_',' ')),el('small','Evaluator sees '+input.events.length+' records; setup heading is not part of its input.'));panel.append(head);const {events:ignored,...metadata}=input;const {events:otherIgnored,...otherMetadata}=inputs[1-index];const metaSame=stableJSON(metadata)===stableJSON(otherMetadata);const detail=el('details',undefined,'comparison-event'+(metaSame?'':' changed'));detail.open=!metaSame;detail.append(el('summary',metaSame?'Matching task and view metadata':'Different task or view metadata'),el('pre',JSON.stringify(metadata,null,2)));panel.append(detail);
    const list=el('div',undefined,'comparison-events');list.tabIndex=0;list.setAttribute('role','region');list.setAttribute('aria-label',(index?'Right':'Left')+' evidence records');
    input.events.forEach((event,i)=>{const matches=stableJSON(event)===stableJSON(inputs[1-index].events[i]);const row=el('article',undefined,'comparison-event'+(matches?'':' changed'));row.append(el('span',event.record_ref+' / '+event.kind.replaceAll('_',' '),'comparison-event-title'),el('span',matches?'Matching record':'Different record','comparison-state'),el('pre',JSON.stringify(event,null,2)));list.append(row);});
    panel.append(list);$('comparison-panels').append(panel);
  });
  $('comparison-result').hidden=false;reveal($('comparison-result'),18);
}
const pct=x=>x===null?'—':(x*100).toFixed(1)+'%';
async function analysis(){
  const split=$('split').value;
  const [data,audit,bundle]=await Promise.all([api('/api/analysis?split='+split),api('/api/audit?split='+split),api('/api/export')]);
  renderAttempts(bundle,split);
  $('metrics').replaceChildren();
  if(!data.summaries.length){const tr=el('tr');const td=cell(tr,'No diagnostics yet. Generate fixtures, then run a local diagnostic.');td.colSpan=9;$('metrics').append(tr);}
  for(const s of data.summaries){const row=el('tr');
    const name=cell(row);name.append(el('strong',s.method.replaceAll('_',' ')),el('span',viewNames[s.view]),el('small',s.scope.replaceAll('_',' ')));
    cell(row,s.n+' / '+s.eligible_n);cell(row,pct(s.coverage));cell(row,pct(s.assigned_mode_accuracy));cell(row,pct(s.answered_error));
    cell(row,String(s.unsupported_definitive));cell(row,s.worker_pair_both_correct+' / '+s.worker_pairs);cell(row,s.controller_pair_both_correct+' / '+s.controller_pairs);
    cell(row,s.failed_attempts+' failed; '+s.missing_predictions+' missing; '+s.ambiguous_pair_cells+' ambiguous pair cells');Array.from(row.children).forEach((td,i)=>td.dataset.label=['Method / view','Scored / available','Coverage of scored','Mode accuracy','Error among answers','Unsupported claims','Worker pairs correct','Controller pairs correct','Collection gaps'][i]);
    const detailIds=[];for(const i of [4,5,6,7]){const td=row.children[i];td.classList.add('metric-detail');td.id='metric-'+$('metrics').children.length+'-'+i;detailIds.push(td.id);}
    const toggle=el('button','More metrics +','metric-toggle');toggle.type='button';toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-controls',detailIds.join(' '));toggle.setAttribute('aria-label','More metrics for '+s.method.replaceAll('_',' ')+' / '+viewNames[s.view]+' / '+s.scope.replaceAll('_',' '));toggle.addEventListener('click',()=>{const expanded=row.classList.toggle('expanded');toggle.setAttribute('aria-expanded',String(expanded));toggle.textContent=expanded?'Fewer metrics −':'More metrics +';});name.append(toggle);$('metrics').append(row);
  }
  $('collisions').replaceChildren();
  for(const s of audit.summaries){const row=el('tr');cell(row,viewNames[s.view]+' / '+s.scope.replaceAll('_',' '));cell(row,String(s.n));cell(row,String(s.distinct_inputs));cell(row,String(s.conflicting_inputs));cell(row,pct(s.empirical_accuracy_ceiling));Array.from(row.children).forEach((td,i)=>td.dataset.label=['View / dataset','Sessions','Distinct inputs','Inputs with conflicting labels','Finite-sample accuracy ceiling'][i]);$('collisions').append(row);}
  if(!audit.summaries.length){const row=el('tr');cell(row,'Complete a session to audit its evidence.').colSpan=5;$('collisions').append(row);}
  $('audit-download').href='/api/audit?split='+split;
}
function renderAttempts(bundle,split){
  const lookup=new Map(bundle.runs.map(run=>[run.id,run]));
  const attempts=bundle.evaluation_attempts.filter(a=>split==='all'||lookup.get(a.run_id)?.split===split).slice(-8).reverse();
  const box=$('evaluation-attempts');box.replaceChildren();
  if(!attempts.length){box.append(el('div','No model evaluation attempts in this split.','card attempt-empty'));return;}
  for(const attempt of attempts){
    const run=lookup.get(attempt.run_id),card=el('article',undefined,'card attempt-card');
    const title=el('div',undefined,'attempt-title');title.append(el('h3',attempt.method.replaceAll('_',' ')+' / '+viewNames[attempt.view]),el('span',attempt.status==='saved'?'Prediction saved':'Attempt failed','attempt-badge '+(attempt.status==='saved'?'saved':'failed')));
    const elapsed=Number.isFinite(attempt.elapsed_seconds)?attempt.elapsed_seconds.toFixed(1)+'s':'time unavailable';
    card.append(title,el('p',(tasks.find(t=>t.id===run?.task)?.title||run?.task||'Session')+' / '+(run?.scope||'unknown scope').replaceAll('_',' ')+' / '+attempt.run_id.slice(0,8)+' / '+elapsed,'attempt-meta'));
    if(attempt.status==='failed'){
      card.append(el('p',attempt.reason||'The response failed validation.','attempt-reason'));
      const hints={timeout:'Review the endpoint and time limit before explicitly retrying.',schema:'Review the output format before explicitly retrying.',truncated:'Review the response token limit before explicitly retrying.',transport:'Check the configured endpoint before explicitly retrying.'};
      card.append(el('p',hints[attempt.error_kind]||'The failed attempt is retained. Retrying requires an explicit selection.','attempt-hint'));
    }else card.append(el('p','Saved against this evidence snapshot. Format validation does not establish attribution accuracy.','attempt-hint'));
    box.append(card);
  }
}
async function evaluateSelected(){
  const live=$('method').value.startsWith('model_');let timer;
  if(live){
    $('evaluation-progress').hidden=false;$('evaluation-progress').setAttribute('aria-busy','true');
    $('evaluation-state').textContent='Waiting for the model';
    $('evaluation-detail').textContent='Evaluating up to '+$('eval-limit').value+' selected sessions. Responses must pass validation before they are saved.';
    const started=Date.now();$('evaluation-elapsed').textContent='0s';
    timer=setInterval(()=>{$('evaluation-elapsed').textContent=Math.floor((Date.now()-started)/1000)+'s';},1000);
  }
  try{
    const r=await api('/api/evaluate',{method:$('method').value,view:$('eval-view').value,limit:Number($('eval-limit').value),scope:$('eval-scope').value,split:$('split').value,retry_failed:$('retry-failed').checked});
    if(live){$('evaluation-state').textContent=r.failures?.length?'Evaluation finished with failures':'Evaluation finished';$('evaluation-detail').textContent=r.evaluated+' saved / '+r.attempted+' attempted; '+(r.failures?.length||0)+' failed. '+r.pending_after_batch+' unattempted sessions remain.';}
    await analysis();notice('Evaluated '+r.evaluated+' completed sessions.'+(r.failures?.length?' '+r.failures.length+' attempts failed and were retained.':(r.pending_after_batch!==undefined?' '+r.pending_after_batch+' unattempted sessions remain.':' Fixture metrics remain software diagnostics.')),Boolean(r.failures?.length));
  }catch(error){if(live){$('evaluation-state').textContent='Evaluation could not finish';$('evaluation-detail').textContent=error.message;}throw error;}
  finally{clearInterval(timer);if(live)$('evaluation-progress').setAttribute('aria-busy','false');}
}
$('new-run').addEventListener('submit',e=>{e.preventDefault();action(async()=>{current=await api('/api/runs',{task:$('task').value,mode:$('mode').value,worker:$('worker').value,backend:$('backend').value,repetition:Number($('repetition').value)});current.task_spec=tasks.find(t=>t.id===current.task);renderSession();await refresh();notice('Session created. All actions remain in the mock environment.');});});
$('seed').addEventListener('click',()=>action(async()=>{const r=await api('/api/demo',{});await refresh();notice(r.added?'Generated '+r.added+' synthetic software fixtures.':'The synthetic fixture matrix already exists; nothing duplicated.');}));
$('refresh').addEventListener('click',()=>action(async()=>{await refresh();notice('Workspace refreshed.');}));$('inspect').addEventListener('click',()=>action(inspectEvidence));$('evidence-view').addEventListener('change',()=>{$('comparison-result').hidden=true;action(inspectEvidence);});$('evidence-run').addEventListener('change',()=>{$('comparison-run').value='';renderComparisonChoices();action(inspectEvidence);});$('comparison-run').addEventListener('change',()=>{$('comparison-result').hidden=true;});$('compare').addEventListener('click',()=>action(compareEvidence));
$('copy-evidence').addEventListener('click',async()=>{
  if(busy)return;
  if(!currentEvidence){notice('Inspect a record first',true);return;}
  const json=JSON.stringify(currentEvidence,null,2);
  try{
    if(!navigator.clipboard?.writeText)throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(json);notice('Copied the selected evidence view.');
  }catch{
    $('copy-json').value=json;$('copy-dialog').showModal();$('copy-json').focus();$('copy-json').select();
  }
});
$('close-copy').addEventListener('click',()=>$('copy-dialog').close());
$('select-copy').addEventListener('click',()=>{$('copy-json').focus();$('copy-json').select();});
$('method').addEventListener('change',()=>{const live=$('method').value.startsWith('model_');$('model-limit').hidden=!live;$('model-selection').hidden=!live;$('evaluate').textContent=live?'Evaluate with configured model':'Run local diagnostic';});
$('evaluate').addEventListener('click',()=>action(evaluateSelected));$('split').addEventListener('change',()=>action(analysis));
$('example-import').addEventListener('click',()=>{$('import-format').hidden=!$('import-format').hidden;$('import-format').textContent=JSON.stringify({predictions:[{run_id:runs[0]?.id||'existing-session-id',view:'actions',label:'unresolved',compatible:Object.keys(modeNames),evidence:[],reason:'Controller origin is not authenticated in this evidence view.'}]},null,2);});
$('import').addEventListener('change',()=>action(async()=>{const file=$('import').files[0];if(!file)return;if(file.size>2000000)throw new Error('Import file exceeds 2 MB');const data=JSON.parse(await file.text());const r=await api('/api/predictions/import',data);await analysis();notice('Imported '+r.imported+' validated predictions.');$('import').value='';}));
function renderJump(){
  const query=$('jump-search').value.trim().toLowerCase();$('jump-results').replaceChildren();
  for(const [id,title] of Object.entries(pageNames)){if(!title.toLowerCase().includes(query))continue;const button=el('button',title);button.type='button';button.append(el('span','↗'));button.addEventListener('click',()=>{$('jump-dialog').close();location.hash=id;page(true);});$('jump-results').append(button);}
  if(!$('jump-results').children.length)$('jump-results').append(el('p','No matching page. Try “evidence” or “protocol”.','form-note'));
}
function openJump(){if(busy)return;$('jump-search').value='';renderJump();$('jump-dialog').showModal();$('jump-search').focus();}
$('open-jump').addEventListener('click',openJump);$('close-jump').addEventListener('click',()=>$('jump-dialog').close());$('jump-search').addEventListener('input',renderJump);
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'&&!event.altKey&&!event.target.matches('input,textarea,select,[contenteditable=true]')){event.preventDefault();if(!$('jump-dialog').open)openJump();}});
page();action(refresh);
