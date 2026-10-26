import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resourceView} from '../web/model.js';
const gpu=(uuid='GPU-a',utilization=60)=>({uuid,utilization,used_mb:1024,total_mb:8192});
const resource=(gpus,at=995,status='online')=>({id:'request',status,telemetry:{at,gpus}});
test('mixed cards aggregate measured values and deduplicate GPU UUIDs',()=>{
 const view=resourceView([resource([gpu()]),resource([gpu(),gpu('GPU-b',80)])],1000);
 assert.equal(view.gpus.length,2);assert.equal(view.utilization,70);assert.equal(view.used,2);assert.equal(view.total,16);
});
test('stale, closed and offline resources retain rows without entering live totals',()=>{
 for(const r of [resource([gpu()],900),resource([gpu()],995,'closed'),resource([gpu()],995,'unknown'),resource([gpu()],1100)]){
  const view=resourceView([r],1000);assert.equal(view.rows.length,1);assert.equal(view.rows[0].fresh,false);assert.equal(view.utilization,null);
 }
 assert.equal(resourceView([resource([gpu()])],1000,false).gpus.length,0);
});
test('unsupported counters remain unknown instead of displaying idle zeroes',()=>{
 const view=resourceView([resource([{uuid:'GPU-na',utilization:null,used_mb:null,total_mb:8192}])],1000);
 assert.equal(view.utilization,null);assert.equal(view.used,null);assert.equal(view.partial,true);
 assert.equal(resourceView([resource([gpu('GPU-idle',0)])],1000).utilization,0);
});
