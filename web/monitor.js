// Read-only monitoring built on Inspire Queue telemetry; no ServerBox client required.
export function resourceView(resource, now=Date.now()/1000, connected=true){
 const telemetry=resource.telemetry||{}, at=Number(telemetry.at);
 const fresh=connected&&resource.status==='online'&&Number.isFinite(at)&&at>0&&now-at>=-5&&now-at<90;
 const number=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
 return {id:resource.id, status:resource.status, host:telemetry.host||'', at, fresh,
  releasePending:resource.release?.state==='pending_interface',
  gpus:(telemetry.gpus||[]).map(gpu=>({name:gpu.name,index:gpu.index,
   utilization:fresh?number(gpu.utilization):null,
   used:fresh?number(gpu.used_mb):null,total:fresh?number(gpu.total_mb):null,
   temperature:fresh?number(gpu.temperature_c):null}))};
}

export class MonitorHistory{
 constructor(){this.samples=new Map();}
 update(resources, now=Date.now()/1000){
  const active=new Set();
  for(const resource of resources){
   const view=resourceView(resource,now);active.add(view.id);
   const samples=(this.samples.get(view.id)||[]).filter(sample=>now-sample.at<1800);
   if(view.fresh&&!samples.some(sample=>sample.at===view.at)){
    const values=view.gpus.map(gpu=>gpu.utilization).filter(value=>value!==null);
    if(values.length)samples.push({at:view.at,value:values.reduce((a,b)=>a+b,0)/values.length});
   }
   samples.sort((a,b)=>a.at-b.at);
   this.samples.set(view.id,samples.slice(-120));
  }
  for(const id of this.samples.keys())if(!active.has(id))this.samples.delete(id);
 }
}
