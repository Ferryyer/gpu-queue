const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const modelModule={exports:{}};
new Function('module',fs.readFileSync(path.join(__dirname,'../launchers/macos/widget/model.js'),'utf8'))(modelModule);
const Model=modelModule.exports;
const identity={owner:'linlishuo',service:'gpuq',uid:21005};
function setup(){
 let clock=0, selected='/Users/test/SSH configs/member config';
 const requests=[],processes=[],renders=[],saved=[],stopped=[];
 let loginCount=0;
 const io={now:()=>clock,render:v=>renders.push(v),savedPort:()=>8790,savePort:p=>saved.push(p),config:()=>selected,
 http:(port,path,done)=>requests.push({port,path,done}),ssh:(args,done)=>{const h={args,done};processes.push(h);return h;},stop:h=>stopped.push(h),login:()=>loginCount++};
 const c=new Model.Controller(io);
 function reply(error,data){const r=requests.shift();assert.ok(r,'expected HTTP request');r.done(error,data);}
 function tick(){clock+=1000;c.tick();}
 function beginSSH(){c.connect();for(let n=0;n<10;n++){reply(true,null);tick();}}
 return {c,requests,processes,renders,saved,stopped,reply,tick,beginSSH,advance:n=>clock+=n,logins:()=>loginCount,setConfig:v=>selected=v};
}
test('reuses a verified existing connection and keeps external tunnels out of Disconnect',()=>{
 const x=setup();x.c.connect();x.reply(null,identity);assert.equal(x.c.phase,'online');assert.equal(x.processes.length,0);
 x.tick();x.reply(null,{tasks:[{name:'film',state:'running'},{state:'queued'},{state:'ready'}]});
 assert.deepEqual(x.c.view().summary,{running:1,queued:1,ready:1,attention:0,current:'film'});
 x.c.disconnect();assert.equal(x.stopped.length,0);assert.equal(x.c.phase,'online');
});
test('rejects another local service before opening a connection',()=>{
 const x=setup();x.c.connect();x.reply(null,{...identity,owner:'someone-else'});x.tick();
 assert.equal(x.c.phase,'discovering');assert.equal(x.c.data,null);assert.equal(x.requests[0].path,'/api/health');
});
test('keeps config paths as argv and starts one SSH process for repeated connection clicks',()=>{
 const x=setup();x.beginSSH();assert.equal(x.c.phase,'connecting');assert.equal(x.processes.length,1);
 x.c.connect();assert.equal(x.processes.length,1);
 const args=x.processes[0].args;assert.equal(args[1],'/Users/test/SSH configs/member config');
 assert.ok(args.includes('BatchMode=yes'));assert.ok(args.includes('127.0.0.1:8790:/tmp/gpuq-21005/web.sock'));
 assert.ok(!args.some(a=>/StrictHostKeyChecking=no|sudo|mf-gpu/.test(a)));
});
test('ignores late HTTP responses after Disconnect and does not reopen the tunnel',()=>{
 const x=setup();x.beginSSH();x.tick();const old=x.requests.shift();assert.ok(old);
 x.c.disconnect();old.done(null,identity);
 assert.equal(x.c.phase,'offline');assert.equal(x.stopped.length,1);assert.equal(x.c.handle,null);
 x.tick();assert.equal(x.requests.length,0);assert.equal(x.processes.length,1);
});
test('a port conflict tries another port and never terminates another process',()=>{
 const x=setup();x.beginSSH();x.processes[0].done('bind: Address already in use');
 assert.equal(x.c.port,8791);assert.equal(x.processes.length,2);assert.equal(x.stopped.length,0);
 x.tick();x.reply(null,identity);assert.equal(x.c.phase,'online');assert.deepEqual(x.saved,[8791]);
});
test('authentication needs an explicit login action and is not retried in a loop',()=>{
 const x=setup();x.beginSSH();x.processes[0].done('Permission denied (publickey)');
 assert.equal(x.c.phase,'auth');x.tick();assert.equal(x.processes.length,1);assert.equal(x.logins(),0);
 x.c.connect();assert.equal(x.c.phase,'login');assert.equal(x.logins(),1);
 x.advance(181000);x.c.tick();assert.equal(x.c.phase,'auth');
});
test('a failed state request clears stale counts and permits reconnecting an external tunnel',()=>{
 const x=setup();x.c.connect();x.reply(null,identity);x.tick();x.reply(null,{tasks:[{name:'film',state:'running'}]});
 x.advance(6000);x.c.tick();x.reply(true,null);
 assert.equal(x.c.phase,'offline');assert.equal(x.c.view().summary,null);
 x.c.connect();assert.equal(x.c.phase,'discovering');
});
test('closing the widget stops only its own SSH child and prevents callbacks reviving it',()=>{
 const x=setup();x.beginSSH();const owned=x.processes[0];x.c.close();owned.done('Connection closed');
 assert.equal(x.c.phase,'closed');assert.deepEqual(x.stopped,[owned]);x.tick();assert.equal(x.processes.length,1);
});
test('uncertain execution is shown as needing attention rather than completed or running',()=>{
 assert.deepEqual(Model.counts([{name:'uncertain',state:'execution_unknown'},{state:'completed'}]),{running:0,queued:0,ready:0,attention:1,current:'暂无正在运行的任务'});
});

test('widget mode defaults safely and creates only local mode links',()=>{
 assert.equal(Model.interactionMode('auto'),'auto');
 for(const value of [undefined,'edit','start','auto\n'])assert.equal(Model.interactionMode(value),'edit');
 assert.equal(Model.queueURL(8791,'auto'),'http://127.0.0.1:8791/?mode=auto');
 assert.equal(Model.queueURL('8790','edit'),'http://127.0.0.1:8790/?mode=edit');
 for(const port of [80,8800,'8790/evil',null])assert.throws(()=>Model.queueURL(port,'auto'));
});
