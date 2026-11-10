'use strict';
const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const COLORS = {read:'#3275b0',write:'#bd613c',register:'#9b4b9d',address:'#547f82',control:'#816899'};
const HEX = (n, width=4) => Number(n).toString(16).toUpperCase().padStart(width,'0');
const hx = (n,w=4) => '0x'+HEX(n,w);
const signed = n => n & 0x8000 ? n - 65536 : n; // Только формат отображения 16-битного слова.
const flags = ['zf','sf','cf','of'];
let state=null, token='', program=null, examples=[], phase=3, tab='execution';
let selected=null, busy=false, playing=false, replaying=false, timer=null, epoch=0;
let assembledSource='', sourceName='program.asm', runCount=0;
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
let memoryPage=0;
const text = (id, value) => { $(id).textContent = value; };
const dirty = () => $('source').value !== assembledSource;
const record = () => selected || state?.last;
function el(tag, cls='', content='') {const n=document.createElement(tag);n.className=cls;n.textContent=content;return n;}
function svg(tag, attrs={}, content=null) {const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs)) n.setAttribute(k,String(v));if(content!==null)n.textContent=String(content);return n;}
function st(parent,x,y,value,cls='s-caption',attrs={}) {const n=svg('text',{x,y,class:cls,...attrs},value);parent.append(n);return n;}
function clipped(s,n=42) {return s.length>n?s.slice(0,n-1)+'…':s;}
function rect(parent,x,y,width,height,cls='',radius=12) {const n=svg('rect',{x,y,width,height,rx:radius,class:cls});parent.append(n);return n;}
function error(message) {text('error-text',message);$('error').hidden=false;}
function hideError() {$('error').hidden=true;}
async function api(path, options={}) {
  let response;
  try {response=await fetch(path,{credentials:'same-origin',...options});}
  catch {throw new Error('Нет связи с Python-сервером. Проверь терминал и запусти run-web.cmd. Исходник остается в редакторе.');}
  const data=await response.json();
  if(!response.ok) {const exc=new Error(data.error||'Ошибка сервера');exc.data=data;throw exc;}
  return data;
}
function accept(data,replaceSource=false) {
  state=data;
  if(data.program) {program=data.program;assembledSource=program.source;if(replaceSource)$('source').value=program.source;}
  updateControls();renderLive();renderVisible();
}
async function action(name,extra={}) {
  if(busy||!state)return false;
  busy=true;hideError();updateControls();
  try {
    const data=await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},
      body:JSON.stringify({action:name,revision:state.revision,...extra})});
    selected=null;
    accept(data,['assemble','example'].includes(name));
    return true;
  } catch(exc) {
    if(exc.data?.state)accept(exc.data.state);
    stop();error(exc.message);return false;
  } finally {busy=false;updateControls();}
}
function updateControls() {
  const unavailable=!state || busy;
  const executable=!unavailable&&!dirty()&&!state.cpu.halted&&!state.error;
  $('step').disabled=!executable||playing||replaying;
  $('run').disabled=!executable||playing||replaying;
  $('run-complete').disabled=!executable||playing||replaying;
  $('pause').disabled=!(playing||replaying);
  $('reset').disabled=unavailable||!program;
  $('assemble').disabled=unavailable||playing||replaying;
  $('example').disabled=unavailable||playing||replaying;
  $('source').readOnly=playing||replaying||busy;
  $('open-source').disabled=playing||replaying||busy;
  $('replay').disabled=!record()||busy||playing||replaying;
  $('next-phase').disabled=!record()||busy||playing||replaying||phase>=3;
  $('return-live').hidden=!selected;
  $('dirty-note').hidden=!state||!dirty();
  text('editor-state',dirty()?'Есть несобранные изменения':'Собранная версия');
  document.querySelectorAll('[data-phase]').forEach(n=>{n.disabled=!record()||busy;n.classList.toggle('active',!!record()&&+n.dataset.phase===phase);n.setAttribute('aria-pressed',String(!!record()&&+n.dataset.phase===phase));});
  $('export-csv').disabled=!state?.history.length;
}
function stop() {epoch++;clearTimeout(timer);timer=null;playing=false;replaying=false;updateControls();}
function delay() {return reduced.matches?0:Number($('speed').value);}
function renderPhase(p) {phase=p;updateControls();renderExecution();}
function replayCurrent(done=()=>{}) {
  if(!record())return done();
  const id=epoch;
  const speed=delay();
  if(!speed) {renderPhase(3);done();return;}
  replaying=true;let p=0;renderPhase(0);
  function tick() {
    if(epoch!==id)return;
    p++;
    if(p<=3){renderPhase(p);timer=setTimeout(tick,speed);}
    else{replaying=false;updateControls();done();}
  }
  timer=setTimeout(tick,speed);
}
async function manualStep() {
  if(busy||!state||dirty()||state.cpu.halted||state.error)return;
  stop();selected=null;
  if(await action('step')){openTab('execution');replayCurrent();}
}
function run() {
  if(busy||!state||dirty()||state.cpu.halted||state.error)return;
  stop();selected=null;playing=true;runCount=0;openTab('execution');updateControls();const id=epoch;
  async function next() {
    if(epoch!==id||!playing)return;
    if(runCount>=10000){stop();error('Выполнено 10 000 команд без остановки. CPU сохранен; доступно продолжение.');return;}
    if(!await action('step'))return;
    if(epoch!==id)return;
    runCount++;
    replayCurrent(()=>{if(epoch!==id)return;if(state.cpu.halted){stop();return;}timer=setTimeout(next,delay()?100:35);});
  }
  next();
}
function renderLive() {
  if(!state)return;
  const c=state.cpu;
  text('connection','Локально / Python');
  text('cpu-status',`CPU после команды: ${state.error?'ошибка':c.halted?'HALT':playing?'исполнение':'готов'}  /  шагов: ${c.steps}`);
  const box=$('live-values');box.replaceChildren();
  [el('span','',`PC ${hx(c.pc)}`),el('span','',`IR ${hx(c.ir,8)}`),...flags.map(f=>el('span',c.flags[f]?'on':'',`${f.toUpperCase()} ${+c.flags[f]}`))].forEach(n=>box.append(n));
}
function openTab(name) {
  tab=name;
  document.querySelectorAll('[data-tab]').forEach(b=>{const on=b.dataset.tab===name;b.setAttribute('aria-selected',String(on));b.tabIndex=on?0:-1;});
  document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!=='page-'+name);
  renderVisible();
}
function renderVisible() {
  if(!state)return;
  renderLive();
  if(tab==='execution')renderExecution();
  if(tab==='program')renderListing();
  if(tab==='registers')renderRegisters();
  if(tab==='memory')renderMemory();
  if(tab==='history')renderHistory();
}
function currentSnapshot() {const r=record();return r?(phase<3?r.before:r.after):state.cpu;}
function currentMemory() {const r=record();return r?(phase<3?r.memory_before:r.memory_after):state.memory;}
function memoryWord(memory,address) {const offset=address*2;return parseInt(memory.slice(offset,offset+2),16)+256*parseInt(memory.slice(offset+2,offset+4),16);}
function rolesFor(n) {
  const r=record();if(!r||phase<2)return [];
  return r.roles.filter(x=>x.index===n&&(phase===3?x.role==='target'||x.role==='source'||x.role==='address':x.role!=='target')).map(x=>x.role);
}
function accessesForView() {const r=record();if(!r)return[];return r.accesses.filter(a=>phase===0?a.kind==='Выборка команды':phase===1?false:phase===2?a.kind==='Чтение данных':a.kind!=='Выборка команды');}
function node(parent,id,x,y,w,h,title,value,subtitle='',klass='') {
  const g=svg('g',{class:'node '+klass,'data-node':id});rect(g,x,y,w,h);
  st(g,x+14,y+23,title,'s-caption');st(g,x+14,y+49,value,'s-value');
  if(subtitle)st(g,x+14,y+h-11,subtitle,'s-tiny');
  const tip=svg('title',{},title+(subtitle?' — '+subtitle:''));g.append(tip);parent.append(g);return g;
}
function memoryGroups() {
  if(!program)return[];
  const groups=[];
  for(const region of program.regions) {
    const prev=groups.at(-1);
    if(prev&&prev.kind===region.kind&&(region.kind==='unused'||region.kind==='code')) {prev.end=region.end;prev.labels.push(...region.labels);}
    else groups.push({...region,labels:[...region.labels]});
  }
  return groups;
}
function paintDiagram() {
  const root=$('diagram');root.replaceChildren();
  const r=record(), c=currentSnapshot(), active=r?r.flows.filter(f=>f.phase===phase):[];
  root.append(svg('title',{},r?`Шаг ${r.id}. ${r.instruction.asm}. ${r.phases[phase].title}. ${r.phases[phase].detail}`:'CPU после сброса. ОЗУ, PC, IR, декодер, управление, АЛУ и 16 регистров.'));
  const defs=svg('defs');for(const [kind,color] of Object.entries(COLORS)) {const m=svg('marker',{id:'arrow-'+kind,viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});m.append(svg('path',{d:'M 1 1 L 9 5 L 1 9 z',fill:color}));defs.append(m);}root.append(defs);
  rect(root,16,50,290,492,'memory-shell',16);st(root,33,80,'Единая ОЗУ','s-title');st(root,33,102,'4096 байт / адреса 0x0000–0x0FFF','s-small');
  const groups=memoryGroups();
  const accesses=accessesForView();
  let visible=groups;
  if(groups.length>5) {const important=g=>accesses.some(a=>a.address<=g.end&&a.address+a.width-1>=g.start);visible=groups.filter(important);for(const g of groups)if(visible.length<5&&!visible.includes(g))visible.push(g);visible.sort((a,b)=>a.start-b.start);}
  const height=visible.length>4?69:Math.min(84,(392-9*(visible.length-1))/Math.max(1,visible.length));
  visible.forEach((g,index)=>{
    const y=122+index*(height+9), hits=accesses.filter(a=>a.address<=g.end&&a.address+a.width-1>=g.start);
    const write=hits.some(a=>a.kind==='Запись данных');
    const block=svg('g',{class:`memory-block ${g.kind} ${write?'write':hits.length?'read':''}`,tabindex:0,role:'button','aria-label':`Открыть память ${hx(g.start)}–${hx(g.end)}`});
    rect(block,32,y,258,height,'',10);
    const title=g.kind==='code'?'Код программы':g.kind==='data'?(g.labels.includes('RESULT')?'Результат':clipped(g.labels.join(', '),26)||'Данные'):'Остальные адреса';
    st(block,45,y+21,title,'s-caption',{'font-weight':650});st(block,45,y+41,`${hx(g.start)}–${hx(g.end)}`,'s-mono');
    const access=hits[0];
    st(block,45,y+height-10,access?`${write?'запись':access.kind==='Выборка команды'?'команда':'чтение'} ${hx(access.address)}: ${hx(access.value,access.width*2)}`:`${g.end-g.start+1} байт${g.kind==='unused'?' / без отдельной метки':''}`,'s-tiny');
    if(access)block.append(svg('title',{},hits.map(a=>`${a.kind}: ${hx(a.address)}, ${a.width} байт, ${hx(a.value,a.width*2)}`).join('\n')));
    const click=()=>{memoryPage=Math.floor(g.start/256);openTab('memory');};block.addEventListener('click',click);block.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();click();}});root.append(block);
  });
  st(root,34,525,groups.length>5?'Все диапазоны — на вкладке «Память»':'Диапазоны — части одной памяти.','s-tiny');
  rect(root,335,30,1005,544,'cpu-shell',18);st(root,353,57,'CPU','s-title');st(root,396,57,'УЧЕБНАЯ МОДЕЛЬ / ПОКОМАНДНОЕ ИСПОЛНЕНИЕ','s-tiny');
  root.append(svg('path',{class:'idle-path',d:'M 306 185 H 550 V 128 H 575 M 780 128 H 828 M 933 170 V 214 M 1080 330 H 1056 V 355 H 1030 M 920 412 V 446 H 1080'}));
  const isActive=id=>active.some(f=>f.src===id||f.dst===id);
  node(root,'pc',365,86,160,84,'PC / адрес команды',hx(c.pc),'байтовый адрес',isActive('pc')?'active':'');
  node(root,'word',575,86,205,84,'Команда из ОЗУ',r?hx(r.instruction.word,8):'—','слово выборки / не отдельный РОН',phase<2&&r?'read-active':'');
  const d=node(root,'decoder',828,86,210,84,'Декодер',r?r.instruction.name:'Ожидание','операция / регистр / режим',phase===1&&r?'active control':'control');
  if(r)d.append(svg('title',{},`opcode=${hx(r.instruction.opcode,2)}, reg=${r.instruction.register}, mode=${r.instruction.mode}, operand=${hx(r.instruction.operand)}`));
  node(root,'control',830,214,204,76,'Устройство управления',r?(r.branch_taken!==null?(r.branch_taken?'Переход':'PC + 4'):r.after.halted?'HALT':'PC + 4'):'Ожидание','выбор операции и следующего PC',isActive('control')?'active control':'control');
  const oi=r?.operation;
  let sourceValue=r?hx(r.instruction.operand):'—';
  let sourceSubtitle=r?`режим: ${['регистр','значение','адрес ОЗУ','адрес из РОН'][r.instruction.mode]}`:'16-битное поле';
  node(root,'operand',575,226,195,75,'Поле операнда',sourceValue,sourceSubtitle,r&&phase>=1?'active':'');
  st(root,588,337,oi&&!oi.used?'MOV, переходы и HALT':'Данные поступают в АЛУ','s-small');
  st(root,588,354,oi&&!oi.used?'не используют АЛУ.':'из регистров или инструкции.','s-small');
  const alu=svg('g',{class:(oi?.used&&phase>=2?'alu-active':'')});
  alu.append(svg('path',{d:'M 818 321 L 1008 321 L 1030 366 L 1008 412 L 818 412 L 796 366 Z',class:'alu-shape'+(oi&&!oi.used?' bypass':'')}));
  st(alu,914,344,'АЛУ'+(oi?.used?' / '+oi.name:''),'s-title',{'text-anchor':'middle'});
  if(oi?.used&&phase>=2) {
    st(alu,914,365,'A '+clipped(oi.a,23),'s-mono',{'text-anchor':'middle'});
    st(alu,914,384,'B '+clipped(oi.b,23),'s-mono',{'text-anchor':'middle'});
    st(root,912,437,(oi.carry!==null?`CF вход = ${oi.carry} / `:'')+(phase===3?clipped('выход '+oi.result,34):'значения до фиксации'),'s-tiny',{'text-anchor':'middle'});
  } else {st(alu,914,373,r?'не задействовано':'ожидание команды','s-small',{'text-anchor':'middle'});}
  root.append(alu);
  node(root,'ir',365,420,209,80,'IR / выполненная команда',hx(c.ir,8),'обновляется после успешного шага',isActive('ir')?'active':'');
  st(root,575,483,'Флаги последней операции','s-small');
  flags.forEach((f,n)=>{const x=826+n*49,g=svg('g',{class:'flag '+(c.flags[f]?'on':'')});rect(g,x,465,43,41,'',9);st(g,x+21.5,482,f.toUpperCase(),'s-tiny',{'text-anchor':'middle'});st(g,x+21.5,498,+c.flags[f],'s-mono',{'text-anchor':'middle'});root.append(g);});
  rect(root,1080,86,236,383,'register-shell',14);st(root,1095,113,'Регистры','s-title');st(root,1299,112,'16 × 16 бит','s-small',{'text-anchor':'end'});
  for(let n=0;n<16;n++) {
    const x=1094+(n>=8?110:0), y=130+(n%8)*41, roles=rolesFor(n);
    const cell=svg('g',{class:'reg-cell '+roles.join(' '),'data-reg':n,tabindex:0,role:'button','aria-label':`Регистр R${n}, ${hx(c.registers[n])}, со знаком ${signed(c.registers[n])}`});
    rect(cell,x,y,99,35,'',7);st(cell,x+8,y+15,'R'+n,'s-mono');st(cell,x+91,y+16,HEX(c.registers[n]),'s-mono',{'text-anchor':'end'});
    st(cell,x+8,y+29,roles.includes('target')?'приемник':roles.includes('address')?'адрес':roles.includes('source')?'источник':'','role-label');
    cell.append(svg('title',{},`R${n} = ${hx(c.registers[n])}; signed ${signed(c.registers[n])}; unsigned ${c.registers[n]}`));
    const click=()=>{openTab('registers');$('reg-card-'+n)?.focus();};cell.addEventListener('click',click);cell.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();click();}});root.append(cell);
  }
  rect(root,1080,484,236,27,c.halted?'halt-on':'halt-tag',8);st(root,1198,502,c.halted?'HALTED = 1 / остановлен':'HALTED = 0 / доступен шаг','s-mono',{'text-anchor':'middle'});
  active.forEach((flow,n)=>drawFlow(root,flow,n,active));
}
function route(f,index,flows) {
  const reg=x=>x.startsWith('r')&&/^r\d+$/.test(x);
  if(f.src==='pc'&&f.dst==='memory')return {d:'M 365 128 H 322 V 154 H 306',label:[392,190]};
  if(f.src==='memory'&&f.dst==='word')return {d:'M 306 184 H 550 V 128 H 575',label:[434,217]};
  if(f.src==='word'&&f.dst==='decoder')return {d:'M 780 128 H 828'};
  if(f.src==='decoder'&&f.dst==='control')return {d:'M 933 170 V 214'};
  if(f.src==='word'&&f.dst==='ir')return {d:'M 594 170 V 188 H 547 V 397 H 466 V 420',label:[436,380]};
  if(f.src==='control'&&f.dst==='pc')return {d:'M 830 251 H 792 V 71 H 445 V 86',label:[680,70]};
  if(f.dst==='memory'&&f.kind==='address')return {d:`M ${reg(f.src)?'1080 188 H 1058':'828 146 H 804'} V 196 H 317 V 311 H 306`,label:[532,196]};
  if(f.dst==='memory'&&reg(f.src))return {d:'M 1316 360 H 1330 V 557 H 317 V 380 H 306',label:[710,557]};
  if(f.src==='memory'&&reg(f.dst))return {d:'M 306 348 H 324 V 529 H 1328 V 320 H 1316',label:[718,529]};
  if(f.src==='decoder'&&reg(f.dst))return {d:'M 1038 132 H 1057 V 245 H 1080',label:null};
  if(reg(f.src)&&reg(f.dst))return {d:'M 1316 255 H 1329 V 335 H 1316'};
  if(f.dst==='alu'&&reg(f.src)) {
    const offset=flows.slice(0,index).filter(x=>x.dst==='alu'&&reg(x.src)).length;
    return {d:`M 1080 ${287+offset*24} H ${1057-offset*10} V ${350+offset*32} H 1025`};
  }
  if(f.dst==='alu'&&f.src==='decoder')return {d:'M 828 147 H 793 V 303 H 820 V 321',label:[689,389]};
  if(f.src==='alu'&&reg(f.dst))return {d:'M 1008 399 H 1058 V 428 H 1080'};
  if(f.src==='alu'&&f.dst==='flags')return {d:'M 913 412 V 465'};
  if(f.src==='flags'&&f.dst==='alu')return {d:'M 932 465 V 440 H 784 V 370 H 797',label:[682,418]};
  if(f.src==='flags'&&f.dst==='control')return {d:'M 1022 483 H 1045 V 253 H 1034'};
  if(f.dst==='halt')return {d:'M 1034 254 H 1068 V 497 H 1080'};
  return {d:'M 575 315 H 750'};
}
function drawFlow(root,f,index,flows) {
  const spec=route(f,index,flows), group=svg('g',{'data-flow':index});
  const path=svg('path',{d:spec.d,class:'wire '+f.kind,'marker-end':`url(#arrow-${f.kind})`});
  path.append(svg('title',{},`${endpoint(f.src)} → ${endpoint(f.dst)}: ${f.label}. ${f.detail}`));group.append(path);
  if(delay()>0&&!reduced.matches) {const packet=svg('circle',{r:4.5,fill:COLORS[f.kind],class:'packet'});packet.append(svg('animateMotion',{path:spec.d,dur:'1.5s',repeatCount:'indefinite'}));group.append(packet);}
  if(spec.label) {const [x,y]=spec.label,label=clipped(f.label,39),w=Math.max(80,label.length*6.4+18);const g=svg('g',{class:'path-label'});rect(g,x-w/2,y-12,w,22,'',6);st(g,x,y+3,label,'s-mono',{'text-anchor':'middle',style:`fill:${COLORS[f.kind]}`});group.append(g);}
  root.append(group);
}
function endpoint(id) {return ({memory:'ОЗУ',pc:'PC',word:'Команда из ОЗУ',ir:'IR',decoder:'Декодер',control:'Управление',alu:'АЛУ',flags:'Флаги',halt:'HALTED'})[id]||id.toUpperCase();}
function renderOperationIO(r) {
  const inputs=$('operation-inputs'),outputs=$('operation-outputs');
  inputs.replaceChildren();outputs.replaceChildren();
  $('operation-io').hidden=!r;
  const add=(container,label,value)=>{const item=el('div','io-value');item.append(el('span','io-label',label),el('strong','',value));container.append(item);};
  if(!r) {
    inputs.append(el('p','empty','Выполни шаг, чтобы увидеть операнды.'));
    outputs.append(el('p','empty','Здесь появится результат команды.'));
    return;
  }
  const op=r.operation;
  [['A',op.a],['B',op.b],...(op.carry===null?[]:[['CF на входе',String(op.carry)]])]
    .filter(([,value])=>value&&value!=='—')
    .forEach(([label,value])=>add(inputs,label,value));
  if(!inputs.childElementCount)inputs.append(el('p','empty','Команда не использует операнды.'));
  const destinations=r.flows.filter(f=>f.phase===3&&(f.dst==='memory'||/^r\d+$/.test(f.dst)));
  if(destinations.length)for(const flow of destinations) {
    if(flow.dst==='memory')add(outputs,'Запись в ОЗУ',flow.label);
    else {const register=Number(flow.dst.slice(1));add(outputs,`R${register}`,hx(r.after.registers[register]));}
  }
  else if(op.result==='только флаги')add(outputs,'Флаги',flags.map(f=>`${f.toUpperCase()}=${+r.after.flags[f]}`).join(' · '));
  else if(op.result&&op.result!=='—')add(outputs,'Результат',op.result);
  else outputs.append(el('p','empty','Нет выходного значения.'));
}

function renderExecution() {
  if(!state)return;
  const r=record();
  text('step-label',r?`${selected?'ИСТОРИЯ / ':''}ШАГ ${r.id} / АДРЕС ${hx(r.address)}`:'НАЧАЛЬНОЕ СОСТОЯНИЕ');
  text('command-title',r?r.instruction.asm:'Путь данных через процессор');
  text('command-source',r?(r.source||'Инструкция декодирована из памяти.'):'Нажми «Шаг». Начнем с адреса данных, затем прочитаем числа 7 и 12.');
  text('view-label',r?`${selected?'Архив / ':''}снимок «${phase<3?'до':'после'}» команды ${r.id}${selected?` / CPU остается на шаге ${state.cpu.steps}`:''}`:'Состояние после сброса');
  text('phase-tag',r?r.phases[phase].title:'Как читать схему');
  text('phase-detail',r?r.phases[phase].detail:'ОЗУ находится вне CPU. Внутри CPU находятся регистры, декодер, устройство управления и АЛУ. Нажми блок памяти или регистр, чтобы открыть подробности.');
  paintDiagram();
  renderOperationIO(r);
  const transfers=$('transfers');transfers.replaceChildren();
  const active=r?r.flows.filter(f=>f.phase===phase):[];
  text('transfer-count',active.length?`${active.length} передач`:'');
  if(!active.length)transfers.append(el('p','empty','Нет передач на этом этапе.'));
  active.forEach((f,n)=>{const row=el('button','transfer '+f.kind);row.append(el('span','',`${endpoint(f.src)} → ${endpoint(f.dst)}`),el('strong','',f.label));row.title=f.detail;row.addEventListener('mouseenter',()=>$('diagram').querySelector(`[data-flow="${n}"]`)?.classList.add('route-highlight'));row.addEventListener('mouseleave',()=>$('diagram').querySelector(`[data-flow="${n}"]`)?.classList.remove('route-highlight'));row.addEventListener('click',()=>text('phase-detail',f.detail));transfers.append(row);});
  $('changes').replaceChildren();text('change-count',r?`${r.changes.length} изменений`:'');
  if(r)for(const change of r.changes){const tr=el('tr');[change.name,change.before,change.after].forEach(s=>tr.append(el('td','',s)));tr.title=change.note;$('changes').append(tr);}
  else{const tr=el('tr'),td=el('td','empty','Ни одна команда еще не выполнена.');td.colSpan=3;tr.append(td);$('changes').append(tr);}
  const fields=$('instruction-fields');fields.replaceChildren();
  if(r){const i=r.instruction;[['opcode [31:24]',i.opcode,8],['reg [23:20]',i.register,4],['mode [19:18]',i.mode,2],['резерв [17:16]',0,2],['operand [15:0]',i.operand,16]].forEach(([label,value,bits])=>{const d=el('div','field');d.append(el('span','',label),el('strong','',Number(value).toString(2).padStart(bits,'0')),el('small','',hx(value,Math.ceil(bits/4))));fields.append(d);});}
  updateControls();
}
function renderListing() {
  const body=$('listing');body.replaceChildren();
  for(const row of program?.listing||[]) {const tr=el('tr',row.address===state.cpu.pc&&!state.cpu.halted?'mark-read':'');[hx(row.address),hx(row.word,8),String(row.line),row.source].forEach((x,n)=>tr.append(el('td',n===3?'wrap mono':'num',x)));body.append(tr);}
}
function renderRegisters() {
  const r=state.last, c=state.cpu, box=$('register-cards');box.replaceChildren();
  c.registers.forEach((value,n)=>{const changed=r&&r.before.registers[n]!==value,card=el('div','register-card'+(changed?' changed':''));card.id='reg-card-'+n;card.tabIndex=0;const name=el('div','reg-name',`R${n}`);if(changed)name.append(el('em','','изменился'));card.append(name,el('strong','',hx(value)),el('small','',`signed ${signed(value)} / unsigned ${value}`),el('small','mono',value.toString(2).padStart(16,'0')));box.append(card);});
  const specials=$('special-cards');specials.replaceChildren();
  [['PC / байтовый адрес',hx(c.pc),state.upcoming||'Следующей команды нет'],['IR / последняя инструкция',hx(c.ir,8),'32 бита'],['Флаги',flags.map(f=>`${f.toUpperCase()}=${+c.flags[f]}`).join(' '),'Относятся к последней операции, которая их обновляла.']].forEach(([title,value,note])=>{const d=el('div','register-card');d.append(el('span','reg-name',title),el('strong','',value),el('small','',note));specials.append(d);});
}
function renderMemory() {
  $('memory-page').value=String(memoryPage);const map=$('memory-map');map.replaceChildren();
  for(const g of program.regions){const hits=(state.last?.accesses||[]).filter(a=>a.address>=g.start&&a.address<=g.end);const b=el('button',Math.floor(g.start/256)===memoryPage?'current':'',hx(g.start));b.dataset.kind=g.kind;b.append(el('small','',g.labels.join(', ')||(g.kind==='code'?'код':g.kind==='data'?'данные':'без меток')));if(hits.some(a=>a.kind==='Запись данных'))b.classList.add('write');else if(hits.length)b.classList.add('read');b.onclick=()=>{memoryPage=g.start/256;renderMemory();};map.append(b);}
  const result=state.result,summary=$('memory-result');
  summary.hidden=!result;
  if(result) {
    const bits=BigInt.asUintN(48,BigInt(result.value)).toString(16).toUpperCase().padStart(12,'0');
    const low=memoryWord(state.memory,result.address);
    const middle=memoryWord(state.memory,result.address+2);
    const high=memoryWord(state.memory,result.address+4);
    text('memory-result-decimal',new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0}).format(result.value));
    text('memory-result-hex',`HEX: ${bits.match(/.{4}/g).join(' ')}`);
    text('memory-result-low',String(signed(low)));
    text('memory-result-high',`${HEX(high)} ${HEX(middle)}`);
  }
  const body=$('memory-table');body.replaceChildren();const symbols=Object.entries(program.symbols);
  for(let addr=memoryPage*256;addr<(memoryPage+1)*256;addr+=2){const value=memoryWord(state.memory,addr),hits=(state.last?.accesses||[]).filter(a=>addr<a.address+a.width&&addr+2>a.address);const kind=hits.some(a=>a.kind==='Запись данных')?'write':hits.length?'read':'';const tr=el('tr',kind?'mark-'+kind:'');const bytes=state.memory.slice(addr*2,addr*2+4).toUpperCase().match(/../g).join(' ');[hx(addr),bytes,HEX(value),String(signed(value)),symbols.filter(([,v])=>v===addr).map(([k])=>k).join(', '),hits.map(a=>a.kind).join(', ')].forEach((x,n)=>tr.append(el('td',n<4?'num':'',x)));body.append(tr);}
  text('memory-state',`Текущее состояние CPU после ${state.cpu.steps} команд. Подсветка относится к последней завершенной команде.`);
  $('goto-result').disabled=!state.result;
}
function renderHistory() {
  const body=$('history');body.replaceChildren();
  if(!state.history.length){const tr=el('tr'),td=el('td','empty','История пуста. Выполни первую команду.');td.colSpan=5;tr.append(td);body.append(tr);return;}
  for(const row of [...state.history].reverse()){const tr=el('tr');[String(row.id),hx(row.address),row.instruction.asm,row.summary].forEach((x,n)=>tr.append(el('td',n===3?'wrap':'num',x)));const td=el('td'),button=el('button','','Смотреть');button.onclick=()=>selectHistory(row.id);td.append(button);tr.append(td);body.append(tr);}
}
async function selectHistory(id) {
  stop();if(busy)return;
  try {selected=await api('/api/history/'+id);phase=2;openTab('execution');updateControls();}
  catch(exc){error(exc.message);}
}
function saveFile(name,content,type) {const u=URL.createObjectURL(new Blob([content],{type}));const a=el('a');a.href=u;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1000);}
function exportCSV() {
  const cell=v=>'"'+String(v).replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';
  const rows=[['Шаг','PC до','Инструкция','Изменения'],...state.history.map(r=>[r.id,hx(r.address),r.instruction.asm,r.summary])];
  saveFile('rpaoias-history.csv','\uFEFF'+rows.map(r=>r.map(cell).join(';')).join('\r\n'),'text/csv;charset=utf-8');
}
async function boot() {
  try {
    [examples,state]=await Promise.all([api('/api/examples'),api('/api/session')]);token=state.token;
    for(const e of examples){const option=el('option','',e.name);option.value=e.id;$('example').append(option);}
    for(let i=0;i<16;i++){const option=el('option','',`${hx(i*256)}–${hx(i*256+255)}`);option.value=String(i);$('memory-page').append(option);}
    accept(state,true);phase=3;renderExecution();
  } catch(exc){error(exc.message);text('connection','Нет связи');}
}
$('step').onclick=manualStep;$('run').onclick=run;$('run-complete').onclick=async()=>{stop();selected=null;phase=3;if(await action('run_to_halt'))openTab('execution');};$('pause').onclick=stop;
$('reset').onclick=async()=>{stop();if(busy)return;selected=null;phase=3;await action('reset');};
$('assemble').onclick=async()=>{stop();if(await action('assemble',{source:$('source').value})){phase=3;renderVisible();}};
$('example').onchange=async()=>{if(dirty()&&!confirm('Заменить несобранный исходник выбранным примером?')){return;}stop();phase=3;sourceName=$('example').value+'.asm';text('source-name',sourceName);await action('example',{name:$('example').value});};
$('source').addEventListener('input',()=>{stop();updateControls();});
$('source').addEventListener('keydown',e=>{if(e.key==='Tab'){e.preventDefault();const a=e.target.selectionStart,b=e.target.selectionEnd;e.target.setRangeText('    ',a,b,'end');updateControls();}});
$('open-source').onclick=()=>{if(!dirty()||confirm('Заменить несобранный исходник файлом?'))$('source-file').click();};
$('source-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;if(file.size>100000){error('Размер исходника должен быть не более 100 КБ');return;}stop();$('source').value=(await file.text()).replace(/^\uFEFF/,'');sourceName=file.name;text('source-name',sourceName);updateControls();e.target.value='';};
$('save-source').onclick=()=>saveFile(sourceName,$('source').value,'text/plain;charset=utf-8');
$('replay').onclick=()=>{stop();replayCurrent();};$('next-phase').onclick=()=>{stop();renderPhase(Math.min(3,phase+1));};
$('return-live').onclick=()=>{stop();selected=null;renderPhase(3);};
$('phases').addEventListener('click',e=>{const b=e.target.closest('[data-phase]');if(b&&!b.disabled){stop();renderPhase(+b.dataset.phase);}});
$('tabs').onclick=e=>{const b=e.target.closest('[data-tab]');if(b)openTab(b.dataset.tab);};
$('tabs').onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...$('tabs').querySelectorAll('[data-tab]')];let n=tabs.indexOf(document.activeElement);n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(n+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].focus();openTab(tabs[n].dataset.tab);};
function editorTab(showSource){$('editor-view').hidden=!showSource;$('listing-view').hidden=showSource;for(const [id,on] of [['source-tab',showSource],['listing-tab',!showSource]]){$(id).classList.toggle('selected',on);$(id).setAttribute('aria-selected',String(on));}if(!showSource)renderListing();}
$('source-tab').onclick=()=>editorTab(true);$('listing-tab').onclick=()=>editorTab(false);
$('memory-page').onchange=()=>{memoryPage=+$('memory-page').value;renderMemory();};
$('goto-pc').onclick=()=>{memoryPage=Math.min(15,Math.floor(state.cpu.pc/256));renderMemory();};
$('goto-result').onclick=()=>{if(state.result){memoryPage=Math.floor(state.result.address/256);renderMemory();}};
$('export-csv').onclick=exportCSV;$('dismiss-error').onclick=hideError;
$('refresh').onclick=async()=>{stop();if(busy)return;try{accept(await api('/api/state'));hideError();}catch(exc){error(exc.message);}};
$('speed').onchange=()=>{stop();renderVisible();};
window.addEventListener('beforeunload',e=>{if(state&&dirty()){e.preventDefault();e.returnValue='';}});
window.addEventListener('keydown',e=>{if(e.key==='F10'){e.preventDefault();if(!$('step').disabled)manualStep();}if(e.key==='F5'){e.preventDefault();if(playing||replaying)stop();else run();}if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();if(!$('assemble').disabled)$('assemble').click();}});
document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openTab(b.dataset.open));
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
boot();
