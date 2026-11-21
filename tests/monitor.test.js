import test from 'node:test';
import assert from 'node:assert/strict';
import {resourceView,MonitorHistory} from '../web/monitor.js';
const resource=(at=1000,status='online')=>({id:'instance',status,telemetry:{at,host:'gpu-host',gpus:[{name:'H100',index:0,utilization:80,used_mb:1024,total_mb:81920,temperature_c:60}]}});
test('only live samples expose metrics; future, stale, closed and unknown fail closed',()=>{
 assert.equal(resourceView(resource(),1001).gpus[0].temperature,60);
 for(const value of [resource(910),resource(1100),resource(1000,'closed'),resource(1000,'unknown')]){
  const view=resourceView(value,1000);assert.equal(view.fresh,false);assert.equal(view.gpus[0].utilization,null);
 }
});
test('missing and invalid metric values remain unavailable, never become zero',()=>{
 const value=resource();Object.assign(value.telemetry.gpus[0],{temperature_c:null,utilization:NaN,used_mb:-1});
 const gpu=resourceView(value,1001).gpus[0];assert.equal(gpu.temperature,null);assert.equal(gpu.utilization,null);assert.equal(gpu.used,null);
});
test('polling the same sample does not fabricate trend points',()=>{
 const history=new MonitorHistory();history.update([resource()],1001);history.update([resource()],1002);
 assert.equal(history.samples.get('instance').length,1);
 history.update([resource(1030)],1031);assert.equal(history.samples.get('instance').length,2);
 history.update([resource(1030,'closed')],1040);assert.equal(history.samples.get('instance').length,2);
 history.update([resource(1030,'closed')],3000);assert.deepEqual(history.samples.get('instance'),[]);
 history.update([],3001);assert.equal(history.samples.size,0);
});
test('release intent remains distinct from closed lifecycle',()=>{
 const value=resource();value.release={state:'pending_interface'};const view=resourceView(value,1001);
 assert.equal(view.releasePending,true);assert.equal(view.status,'online');
});
