export function canStop(task){return ['ready','queued','waiting_gpu','checking_resources','dispatching','starting','running','execution_unknown'].includes(task.state);}
export function stepState(task,index){
 const record=task.step_records?.[index];
 if(record?.state==='completed'||task.state==='completed')return 'done';
 if(['cancelled','stopped'].includes(task.state))return index===task.stage&&record?'stopped':'skipped';
 if(record?.state==='stopped')return 'stopped';
 if(record?.state==='failed')return 'failed';
 if(['failed','interrupted','blocked','execution_unknown'].includes(task.state))return index===task.stage?'failed':index>task.stage?'skipped':'done';
 if(['running','stopping'].includes(task.state)&&task.stage===index)return 'current';
 return 'pending';
}

// The same GPU can appear in a historical and a current allocation.
export function resourceView(resources, at=Date.now()/1000, connected=true){
 const rows=resources.map(r=>({...r,fresh:connected&&r.status==='online'&&Number.isFinite(r.telemetry?.at)&&at-r.telemetry.at>=-5&&at-r.telemetry.at<90}));
 const unique=new Map();
 for(const r of rows.filter(r=>r.fresh))for(const g of r.telemetry.gpus||[])unique.set(g.uuid,g);
 const gpus=[...unique.values()];
 const known=gpus.filter(g=>Number.isFinite(g.utilization));
 const memory=gpus.filter(g=>Number.isFinite(g.used_mb)&&Number.isFinite(g.total_mb));
 return {rows,gpus,utilization:known.length?Math.round(known.reduce((n,g)=>n+g.utilization,0)/known.length):null,
  used:memory.length?memory.reduce((n,g)=>n+g.used_mb,0)/1024:null,
  total:memory.length?memory.reduce((n,g)=>n+g.total_mb,0)/1024:null,
  partial:known.length<gpus.length||memory.length<gpus.length};
}
