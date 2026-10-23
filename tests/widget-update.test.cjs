const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),os=require('node:os');
const exported={exports:{}};
new Function('module',fs.readFileSync(path.join(__dirname,'../launchers/macos/widget/update-model.js'),'utf8'))(exported);
const U=exported.exports;
const release={schema:1,version:'1.1.0',notes:['One update'],sha256:'a'.repeat(64),bytes:123,
 url:'https://raw.githubusercontent.com/Ferryyer/Ferryyer/main/downloads/GPU-Queue-Widget-1.1.0-macOS.zip'};
function setup(current='1.0.0') {
 let clock=0,ready=false,stopped=false,quits=0,permits=0,cancels=0;
 const fetches=[],operations=[];
 const c=new U.Controller({now:()=>clock,render:()=>{},cancel:()=>cancels++,fetch:cb=>fetches.push(cb),
 operation:(phase,release,cb)=>operations.push({phase,release,cb}),ready:()=>ready,quitWidget:()=>quits++,
 widgetStopped:()=>stopped,permit:()=>permits++},current);
 const reply=(error=null,data=release)=>fetches.shift()(error,data);
 const finish=(error=null)=>{assert.ok(operations.length);operations.shift().cb(error);};
 return {c,fetches,operations,reply,finish,ready:()=>ready=true,stopped:()=>stopped=true,
 advance:n=>clock+=n,quits:()=>quits,permits:()=>permits,cancels:()=>cancels};
}
test('version comparison is numeric and only bounded three-part versions are accepted',()=>{
 assert.equal(U.compare('1.10.0','1.9.9'),1);assert.equal(U.compare('1.1.0','1.1.0'),0);
 for(const v of ['1.2','1.02.3','1.2.3-beta','10000.0.0','1.2.3\n','-1.2.3']) assert.throws(()=>U.version(v));
});
test('rejects foreign hosts, mutable aliases, injected versions and invalid checksums',()=>{
 for(const patch of [{schema:2},{url:release.url.replace('Ferryyer/Ferryyer','other/repo')},
 {url:'http://'+release.url.slice(8)},{url:release.url+'?x=1'},{url:release.url.replace('1.1.0-','')},
 {version:'1.1.0/../../x'},{sha256:'abc'},{sha256:'a'.repeat(64)+'\n'},
 {bytes:21*1024*1024},{bytes:12.5},{notes:['x'.repeat(1001)]}])
 assert.throws(()=>U.manifest({...release,...patch}));
});
test('checking finds a new version without downloading, installing or closing anything',()=>{
 const x=setup();x.c.check();x.c.check();assert.equal(x.fetches.length,1);x.reply();
 assert.equal(x.c.phase,'available');assert.deepEqual(x.operations,[]);assert.equal(x.quits(),0);
});
test('the current version and older feeds never offer installation',()=>{
 for(const version of ['1.1.0','1.2.0']){
  const x=setup(version);x.c.check();x.reply();x.c.install();
  assert.equal(x.c.phase,'current');assert.deepEqual(x.operations,[]);
 }
});
test('downloads, verifies and prepares before quitting the old panel, then waits for its exit',()=>{
 const x=setup();x.c.check();x.reply();x.c.install();x.c.install();
 for(const phase of ['downloading','verifying','extracting']){
  assert.equal(x.operations[0].phase,phase);assert.equal(x.quits(),0);x.finish();
 }
 assert.equal(x.operations[0].phase,'preparing');x.c.tick();assert.equal(x.quits(),0);
 x.ready();x.c.tick();x.c.tick();assert.equal(x.quits(),1);assert.equal(x.permits(),0);
 x.stopped();x.c.tick();assert.equal(x.permits(),1);assert.equal(x.c.phase,'installing');
 x.finish();assert.equal(x.c.phase,'done');assert.equal(x.c.current,'1.1.0');
 x.c.check();x.reply();assert.equal(x.c.phase,'current');
});
test('checksum failure prevents extraction, app termination and installation',()=>{
 const x=setup();x.c.check();x.reply();x.c.install();x.finish();x.finish('checksum mismatch');
 assert.equal(x.c.phase,'error');assert.deepEqual(x.operations,[]);assert.equal(x.quits(),0);assert.equal(x.permits(),0);
});
test('compilation failure preserves the running panel; an early installer success is also rejected',()=>{
 for(const error of ['compile failed',null]){
  const x=setup();x.c.check();x.reply();x.c.install();x.finish();x.finish();x.finish();x.finish(error);
  assert.equal(x.c.phase,'error');assert.equal(x.quits(),0);assert.equal(x.permits(),0);
 }
});
test('an old panel that refuses to quit prevents replacement and times out',()=>{
 const x=setup();x.c.check();x.reply();x.c.install();x.finish();x.finish();x.finish();
 x.ready();x.c.tick();x.advance(31000);x.c.tick();
 assert.equal(x.c.phase,'error');assert.equal(x.permits(),0);assert.equal(x.cancels(),1);
 x.finish();assert.equal(x.c.phase,'error');
});
test('offline checks can be retried, while stale callbacks cannot overwrite a newer check',()=>{
 const x=setup();x.c.check();const old=x.fetches[0];x.reply('offline');assert.equal(x.c.phase,'error');
 x.c.check();old(null,release);assert.equal(x.c.phase,'checking');x.reply();assert.equal(x.c.phase,'available');
});
test('the actual release ZIP has only allowed paths, regular files and bounded sizes',()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'gpuq-update-'));
 try {
  cp.execFileSync('python3',[path.join(__dirname,'../scripts/package-widget.py'),'--output-dir',temp]);
  const archive=path.join(temp,'GPU任务台-桌面小组件-macOS.zip');
  const names=cp.execFileSync('unzip',['-Z','-1',archive],{encoding:'utf8'});
  const metadata=cp.execFileSync('unzip',['-Z','-l',archive],{encoding:'utf8'});
  U.archiveEntries(names);U.archiveMetadata(metadata);
  const escaped=names.replace(/[^\x00-\x7f]/g,c=>'#U'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  U.archiveEntries(escaped);U.archiveEntries(escaped.replace(/\n/g,'\r\n'));
  // The former literal comparison rejected the same valid archive listing.
  assert.notEqual(escaped,names);
  for(const list of [escaped.replace('VERSION','..#U002fVERSION'),escaped.replace('VERSION','Widget.bundle.js'),escaped.replace('VERSION','#U0000VERSION'),escaped.replace('VERSION','#L110000')])assert.throws(()=>U.archiveEntries(list));
  for(const list of [names+'../bad\n',names.replace('VERSION','../../VERSION'),names.replace('VERSION','Widget.bundle.js')])
   assert.throws(()=>U.archiveEntries(list));
  assert.throws(()=>U.archiveMetadata(metadata.replace(/^-([rwxstST-]{9})/m,'l$1')));
  assert.throws(()=>U.archiveMetadata(metadata.replace(/(\s+unx\s+)\d+/,'$1'+'99999999')));
 } finally {fs.rmSync(temp,{recursive:true,force:true});}
});
