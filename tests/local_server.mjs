import http from 'node:http';
import worker from '../dist/server/index.js';
import {database,payload,id,digest} from './helpers.mjs';
const env={DB:database(),GPUQ_WORKER_KEY:'local-test-only'};
const base='http://127.0.0.1:8765';
const tasks=[1,2,3,4].map(n=>({id:id(n),digest:digest(n),payload:payload(n)}));
tasks[0].payload.state='running';tasks[0].payload.step_records=[{name:'训练',state:'running',log:'GPU test log: training step is running',outputs:[]}];tasks[0].payload.elapsed='3 分钟';
await worker.fetch(new Request(base+'/api/worker/sync',{method:'POST',headers:{'x-gpuq-worker-key':env.GPUQ_WORKER_KEY},body:JSON.stringify({tasks,heartbeat:{resources:[],service:'online'}})}),env);
for(const n of [2,3])await worker.fetch(new Request(base+'/api/tasks/'+id(n)+'/start',{method:'POST',headers:{'oai-authenticated-user-id':'local-test-owner',origin:base,'x-gpuq-action':'1'},body:JSON.stringify({digest:digest(n)})}),env);
http.createServer(async(req,res)=>{try{
 const chunks=[];for await(const chunk of req)chunks.push(chunk);const body=Buffer.concat(chunks);
 if(req.url==='/test/fail'&&req.method==='POST'){
  const task=tasks[0].payload;task.state='failed';task.stage=1;task.failureReason='测试：第二步失败';task.step_records=[{name:'训练',state:'completed',log:'training complete',outputs:[]},{name:'评测',state:'failed',log:'evaluation failed',outputs:[]}];
  await env.DB.prepare('UPDATE gpuq_tasks SET payload=? WHERE id=?').bind(JSON.stringify(task),task.id).run();res.end('ok');return;
 }
 const request=new Request(base+req.url,{method:req.method,headers:{...req.headers,'oai-authenticated-user-id':'local-test-owner'},body:['GET','HEAD'].includes(req.method)?undefined:body});
 const response=await worker.fetch(request,env);res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));
}catch(error){console.error(error.message);res.writeHead(500);res.end('Local test failure');}}).listen(8765,'127.0.0.1',()=>console.log('Local test UI ready on '+base));
