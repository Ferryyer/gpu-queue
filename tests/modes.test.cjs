const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(saved,entry){
 const elements=new Map(),handlers=new Map(),storage=new Map(saved?[['gpuq.interactionMode',saved]]:[]);
 const element=key=>{if(!elements.has(key))elements.set(key,{dataset:{},disabled:false,draggable:true,classList:{contains:()=>key==='grip',add(){},remove(){}},setAttribute(name,value){this[name]=value;},addEventListener(type,fn){handlers.set(key+':'+type,fn);}});return elements.get(key);};
 const start=element('start'),grip=element('grip'),boundary=element('boundary');boundary.disabled=true;
 const context={URL,location:{href:'http://localhost:8790/'+(entry||'')},document:{body:element('body'),querySelector:element,querySelectorAll:s=>s==='[data-start],[data-detail-start],[data-move],.grip'?[start,grip,boundary]:[],addEventListener:(type,fn)=>handlers.set(type,fn)},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},setTimeout:()=>0,clearTimeout(){},fetch(){throw Error('Unexpected network mutation');}};
 const source=fs.readFileSync('web/app.js','utf8').replace(/^import .*;\n/,'').replace('render();load();setInterval(load,5000);','render=()=>renderMode();renderMode();');
 vm.createContext(context);vm.runInContext(source,context);
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

test('release status distinguishes 90-minute grace, unsupported release, and closed resources',()=>{
 const s=setup();
 const message=resources=>vm.runInContext(`releasePolicyText(${JSON.stringify({resources})})`,s.context);
 assert.match(message([]),/结束 90 分钟后/);
 const grace={status:'online',release:{state:'grace_period',release_after:1792830000}};
 assert.match(message([grace]),/保留 90 分钟，计划/);
 assert.match(message([grace]),/当前未确认释放/);
 const due={status:'online',release:{state:'pending_interface'}};
 assert.match(message([grace,due]),/释放待处理/);
 assert.doesNotMatch(message([{...due,status:'closed'},grace]),/释放待处理/);
});
