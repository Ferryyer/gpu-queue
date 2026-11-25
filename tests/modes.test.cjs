const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(saved,entry){
 const elements=new Map(),handlers=new Map(),storage=new Map(saved?[['gpuq.interactionMode',saved]]:[]);
 const element=key=>{if(!elements.has(key))elements.set(key,{dataset:{},disabled:false,draggable:true,classList:{contains:()=>key==='grip',add(){},remove(){}},setAttribute(name,value){this[name]=value;},addEventListener(type,fn){handlers.set(key+':'+type,fn);}});return elements.get(key);};
 const start=element('start'),grip=element('grip'),boundary=element('boundary');boundary.disabled=true;
 const context={matchMedia:()=>({matches:false,addEventListener(){}}),URL,location:{href:'http://localhost:8790/'+(entry||'')},document:{body:element('body'),querySelector:element,querySelectorAll:s=>s==='[data-start],[data-detail-start],[data-move],.grip'?[start,grip,boundary]:[],addEventListener:(type,fn)=>handlers.set(type,fn)},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},setTimeout:()=>0,clearTimeout(){},fetch(){throw Error('Unexpected network mutation');}};
 const source=fs.readFileSync('web/app.js','utf8').replace(/^import .*;\n/gm,'').replace('render();load();setInterval(load,5000);','render=()=>renderMode();renderMode();');
 vm.createContext(context);vm.runInContext(fs.readFileSync('web/model.js','utf8').replace(/^export /gm,''),context);vm.runInContext(fs.readFileSync('web/monitor.js','utf8').replace(/^export /gm,''),context);vm.runInContext(fs.readFileSync('web/detail-modal.js','utf8').replace(/^export /gm,''),context);vm.runInContext(source,context);
 return {context,element,start,grip,boundary,storage,key:(target={closest:()=>null})=>{let prevented=false;handlers.get('keydown')({key:'Tab',shiftKey:true,target,preventDefault(){prevented=true;}});return prevented;}};
}
test('Shift+Tab switches persistent modes without task mutations and restores queue boundaries',async()=>{
 const s=setup();assert.equal(s.element('#mode-label').textContent,'Edit mode');
 assert.equal(s.key(),true);assert.equal(s.element('#mode-label').textContent,'Auto mode');
 assert.equal(s.start.disabled,true);assert.equal(s.grip.draggable,false);
 await vm.runInContext("start('task');requestReorder('a','b')",s.context);
 assert.equal(s.storage.get('gpuq.interactionMode'),'auto');
 s.key();assert.equal(s.start.disabled,false);assert.equal(s.grip.draggable,true);assert.equal(s.boundary.disabled,true);
});
test('saved Auto mode survives initialization; form fields and dialogs retain Shift+Tab navigation',()=>{
 const s=setup('auto');assert.equal(s.start.disabled,true);
 assert.equal(s.key({closest:()=>({})}),false);assert.equal(s.element('#mode-label').textContent,'Auto mode');
});

test('widget mode deep links override saved browser mode; invalid modes are ignored',()=>{
 const edit=setup('auto','?mode=edit');assert.equal(edit.start.disabled,false);assert.equal(edit.storage.get('gpuq.interactionMode'),'edit');
 const auto=setup(null,'?mode=auto');assert.equal(auto.start.disabled,true);assert.equal(auto.storage.get('gpuq.interactionMode'),'auto');
 const invalid=setup(null,'?mode=start');assert.equal(invalid.start.disabled,false);
});

test('blocked detail submits the existing version-bound stop action and keeps the pending reason',async()=>{
 const s=setup(),calls=[];
 const task={id:'GQ-0000000000000001',digest:'1'.repeat(64),name:'fixture',state:'blocked',stage:0,steps:['first'],step_records:[],events:[],checks:[],resources:{gpus:1},agent:'Codex',failureReason:'原计算回执待核查'};
 s.context.fixture=task;
 vm.runInContext('state.tasks=[fixture];state.selected=fixture.id;renderDetail()',s.context);
 assert.match(s.element('#detail').innerHTML,/data-detail-stop=/);
 assert.match(s.element('#detail').innerHTML,/停止任务/);
 s.element('#stop-dialog').showModal=()=>calls.push('dialog');
 s.element('#stop-dialog').close=()=>calls.push('close');
 s.context.fetch=async(path,options)=>{calls.push({path,...options});return {ok:true,json:async()=>({revision:1,tasks:[{...task,state:'stopping',phase:'停止状态待核查：原计算回执缺失'}]})};};
 await vm.runInContext('requestStop(fixture.id);confirmStop()',s.context);
 assert.equal(calls[0],'dialog');
 assert.equal(calls[1].path,'/api/tasks/'+task.id+'/stop');
 assert.equal(calls[1].method,'POST');
 assert.deepEqual(JSON.parse(calls[1].body),{digest:task.digest});
 for(const tab of ['overview','logs','results','events']){
  vm.runInContext(`detailTab='${tab}';renderDetail()`,s.context);
  assert.match(s.element('#detail').innerHTML,/正在停止/);
  assert.match(s.element('#detail').innerHTML,/停止状态待核查：原计算回执缺失/);
  assert.doesNotMatch(s.element('#detail').innerHTML,/data-detail-stop=/);
 }
});
