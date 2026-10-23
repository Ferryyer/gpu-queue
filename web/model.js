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
