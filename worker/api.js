const json = (data, status=200) => new Response(JSON.stringify(data), {status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'}});
const MAX_BODY = 3*1024*1024;
const LIVE_STATES = new Set(['ready','queued','waiting_gpu','checking_resources']);
const secretEqual = (a,b) => {if(!a||!b||a.length!==b.length)return false;let x=0;for(let i=0;i<a.length;i++)x|=a.charCodeAt(i)^b.charCodeAt(i);return x===0;};
async function body(request){const text=await request.text();if(text.length>MAX_BODY)throw new Error('payload_too_large');return JSON.parse(text);}
async function revision(db){return Number((await db.prepare("SELECT value FROM gpuq_meta WHERE key='revision'").first())?.value||0);}
async function state(db){const rows=(await db.prepare('SELECT * FROM gpuq_tasks ORDER BY position,created_at').all()).results;const meta=await db.prepare("SELECT value FROM gpuq_meta WHERE key='heartbeat'").first();return {revision:await revision(db),tasks:rows.map(row=>{const task=JSON.parse(row.payload);if(row.approved_at&&task.state==='ready')task.state='queued';if(row.claimed_at&&LIVE_STATES.has(task.state))task.state='dispatching';return {...task,approved_at:row.approved_at,claimed_at:row.claimed_at,position:row.position,digest:row.digest};}),heartbeat:meta?JSON.parse(meta.value):null};}
export async function api(request,env){
 const url=new URL(request.url),path=url.pathname,db=env.DB;
 if(env.GPUQ_RETIRED==='1'&&!path.startsWith('/api/worker/'))return json({error:'任务台已迁移到个人服务器。请建立 SSH 转发后打开 http://127.0.0.1:8790/'},503);
 if(!db)return json({error:'任务数据库尚未就绪'},503);
 try{
  if(path==='/api/worker/claim'){
   if(request.method!=='POST'||!secretEqual(request.headers.get('x-gpuq-worker-key'),env.GPUQ_WORKER_KEY))return json({error:'unauthorized'},401);
   const input=await body(request);
   const row=await db.prepare('SELECT * FROM gpuq_tasks WHERE id=?').bind(input.id).first();
   if(!row||row.digest!==input.digest||!row.approved_at)return json({error:'unapproved_task'},409);
   if(row.claimed_at)return json({claimed:true,at:row.claimed_at});
   const at=new Date().toISOString();
   const results=await db.batch([
    db.prepare("UPDATE gpuq_tasks SET claimed_at=? WHERE id=? AND claimed_at IS NULL AND (SELECT CAST(value AS INTEGER) FROM gpuq_meta WHERE key='revision')=?").bind(at,row.id,input.revision),
    db.prepare("UPDATE gpuq_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision' AND CAST(value AS INTEGER)=?").bind(input.revision)
   ]);
   return results[0].meta.changes?json({claimed:true,at}):json({error:'queue_changed'},409);
  }
  if(path==='/api/worker/sync'){
   if(request.method!=='POST')return json({error:'method_not_allowed'},405);
   if(!secretEqual(request.headers.get('x-gpuq-worker-key'),env.GPUQ_WORKER_KEY))return json({error:'unauthorized'},401);
   const input=await body(request);
   if(!Array.isArray(input.tasks)||input.tasks.length>300)return json({error:'invalid_tasks'},400);
   const statements=[];
   for(const task of input.tasks){
    if(!/^GQ-[a-f0-9]{16}$/.test(task.id)||!/^[a-f0-9]{64}$/.test(task.digest)||task.payload?.id!==task.id)return json({error:'invalid_task'},400);
    const previous=await db.prepare('SELECT digest FROM gpuq_tasks WHERE id=?').bind(task.id).first();
    if(previous&&previous.digest!==task.digest)return json({error:'immutable_task_changed'},409);
    const payload=JSON.stringify(task.payload);
    if(payload.length>200000)return json({error:'task_payload_too_large'},400);
    statements.push(db.prepare('INSERT INTO gpuq_tasks(id,digest,payload,created_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload WHERE gpuq_tasks.digest=excluded.digest').bind(task.id,task.digest,payload,task.payload.created_at));
   }
   const heartbeat={...input.heartbeat,at:new Date().toISOString()};
   statements.push(db.prepare("INSERT INTO gpuq_meta(key,value) VALUES('heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(JSON.stringify(heartbeat)));
   await db.batch(statements);
   return json(await state(db));
  }
  // Sites enforces owner-only access; service callers carry no visitor identity.
  if(!request.headers.get('oai-authenticated-user-id'))return json({error:'请使用本人账号登录任务台'},401);
  if(path==='/api/state'&&request.method==='GET')return json(await state(db));
  if(request.method!=='POST')return json({error:'method_not_allowed'},405);
  if(request.headers.get('origin')!==url.origin||request.headers.get('x-gpuq-action')!=='1')return json({error:'invalid_origin'},403);
  const match=path.match(/^\/api\/tasks\/(GQ-[a-f0-9]{16})\/start$/);
  if(match){
   const row=await db.prepare('SELECT * FROM gpuq_tasks WHERE id=?').bind(match[1]).first();
   if(!row)return json({error:'task_not_found'},404);
   const input=await body(request);
   if(input.digest!==row.digest)return json({error:'任务版本已变化，请刷新后查看'},409);
   if(row.approved_at)return json(await state(db));
   const payload=JSON.parse(row.payload);
   if(payload.state!=='ready')return json({error:'只有准备完成的任务可以启动'},409);
   const at=new Date().toISOString();
   await db.batch([
    db.prepare('UPDATE gpuq_tasks SET approved_at=?,position=(SELECT COALESCE(MAX(position),0)+1 FROM gpuq_tasks) WHERE id=? AND approved_at IS NULL').bind(at,row.id),
    db.prepare("UPDATE gpuq_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'"),
    db.prepare('INSERT INTO gpuq_audit(task_id,action,at) VALUES(?,?,?)').bind(row.id,'browser_start:'+row.digest,at)
   ]);
   return json(await state(db));
  }
  if(path==='/api/queue/reorder'){
   const input=await body(request);
   if(!Array.isArray(input.ids)||new Set(input.ids).size!==input.ids.length||!input.ids.every(id=>/^GQ-[a-f0-9]{16}$/.test(id)))return json({error:'invalid_queue'},400);
   const current=await state(db);
   const eligible=current.tasks.filter(t=>t.approved_at&&LIVE_STATES.has(t.state)).map(t=>t.id);
   if(current.revision!==input.revision||eligible.length!==input.ids.length||eligible.some(id=>!input.ids.includes(id)))return json({error:'队列已更新，请刷新后重试'},409);
   const list=JSON.stringify(input.ids);
   const results=await db.batch([
    db.prepare("UPDATE gpuq_tasks SET position=(SELECT CAST(key AS INTEGER) FROM json_each(?) WHERE value=gpuq_tasks.id) WHERE id IN (SELECT value FROM json_each(?)) AND (SELECT CAST(value AS INTEGER) FROM gpuq_meta WHERE key='revision')=?").bind(list,list,input.revision),
    db.prepare("UPDATE gpuq_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision' AND CAST(value AS INTEGER)=?").bind(input.revision),
   ]);
   if(!results[1].meta.changes)return json({error:'队列已更新，请刷新后重试'},409);
   return json(await state(db));
  }
  return json({error:'not_found'},404);
 }catch(error){console.error('gpuq_api',error?.message);return json({error:'任务服务处理失败，请稍后重试'},500);}
}
