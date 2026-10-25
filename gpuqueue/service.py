import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from .core import Store, HOME, DEFAULT_ROOT, SITE_URL, TERMINAL, atomic_json, read_json, canonical, now
from .platform import Markflow, PlatformError

from .control import Control, QueueChanged

def redact(text):
    text = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1[redacted]', text)
    text = re.sub(r'(?i)((?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*)[^\s,;]+', r'\1[redacted]', text)
    return re.sub(r'\bsk-[A-Za-z0-9_-]{15,}', '[redacted]', text)

def tail(path, limit=8000):
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size-limit))
        return redact(stream.read(limit).decode(errors='replace'))

class Service:
    def __init__(self, config, store=None, platform=None):
        self.config = config
        self.store = store or Store()
        self.platform = platform or Markflow(self.store, config)
        self.remote_revision = None
        self.synced = {}
        self.error = None

    def remote(self, path, payload):
        control = Control(self.store)
        if path == '/api/worker/sync':
            return control.sync(payload['heartbeat'])
        if path == '/api/worker/claim':
            return control.claim(payload['id'], payload['digest'], payload['revision'])
        raise ValueError('Unknown internal queue operation')

    def sync(self):
        tasks = self.store.tasks()
        changed = []
        fingerprints = {}
        for task in tasks:
            digest = hashlib.sha256(canonical(task['public']).encode()).hexdigest()
            fingerprints[task['id']] = digest
            if self.synced.get(task['id']) != digest:
                changed.append({'id': task['id'], 'digest': task['digest'], 'payload': task['public']})
        resources = []
        for resource in self.platform.resources.values():
            resources.append({key: resource.get(key) for key in ['id', 'status', 'type', 'gpus', 'telemetry', 'error', 'release']})
        response = self.remote('/api/worker/sync', {'tasks': changed, 'heartbeat': {'service': 'online', 'error': self.error, 'resources': resources, 'resource_policy': self.store.metadata('resource_policy'), 'updated_at': now()}})
        self.synced.update(fingerprints)
        self.remote_revision = response['revision']
        for remote in response['tasks']:
            local = self.store.get(remote['id'])
            if not local or local['digest'] != remote['digest']:
                continue
            if remote.get('approved_at') and not local['internal'].get('approved_at'):
                local['internal']['approved_at'] = remote['approved_at']
                local['public'].update(state='queued', approved_at=remote['approved_at'])
                local['public']['events'].append('你在网页点击了开始，授权执行这一版完整流程')
            local['internal']['position'] = remote['position']
            if remote.get('stop_requested_at'):
                at = remote['stop_requested_at']
                if not local['internal'].get('stop_requested_at'):
                    local['public']['events'].append('你在网页请求停止任务；已有产物保留，后续步骤不再执行')
                local['internal']['stop_requested_at'] = at
                atomic_json(self.store.root/'tasks'/local['id']/'run/stop.json', {'task':local['id'],'digest':local['digest'],'at':at})
                if remote['state'] != 'completed':
                    local['public'].update(state=remote['state'], phase='已移出队列' if remote['state']=='cancelled' else '任务已停止，已有产物保留' if remote['state']=='stopped' else '正在确认任务进程退出；已有产物保留')
            self.store.save(local)

    def refresh_task(self, task):
        internal, public = task['internal'], task['public']
        request_id, job_id = internal.get('request_uuid'), internal.get('job_uuid')
        if internal.get('dispatch') == 'submitting' and not job_id:
            expected = internal['argv']
            matches = []
            for file in self.platform.job_folder(request_id).glob('*.json'):
                if read_json(file, {}).get('argv') == expected:
                    matches.append(file.stem)
            if len(matches) == 1:
                internal.update(job_uuid=matches[0], dispatch='submitted')
                job_id = matches[0]
            else:
                internal['dispatch'] = 'unknown'
                public.update(state='blocked', failureReason='GPU 提交曾中断，无法唯一确认回执；已停止自动重试')
                self.store.save(task)
                return
        if not job_id:
            return
        folder = self.store.root/'tasks'/task['id']
        status = read_json(folder/'run/status.json')
        job_status = read_json(self.platform.job_folder(request_id)/job_id/'status.json', {})
        if status:
            public.update(state=status['state'], stage=status.get('stage', 0), step_records=status.get('steps', []), progress=None)
            if status.get('error'):
                public['failureReason'] = redact(status['error'])[:1200]
            if status.get('gpu_verified'):
                public['checks'][-1] = 'GPU 设备已核验'
            if status['state'] in ['starting', 'running'] and time.time()-status.get('updated_at', 0)>180:
                public.update(state='execution_unknown', failureReason='执行心跳已中断，正在核查原任务；不会重新申请或重复运行')
            end = status.get('finished_at', time.time())
            public['elapsed'] = str(max(0, int((end-status['started_at'])/60)))+' 分钟'
            for index, step in enumerate(public['step_records']):
                step['log'] = tail(folder/'run'/f'step-{index}.log')
            if status['state'] in ['completed', 'failed'] and not internal.get('finished_recorded'):
                public['events'].append('全部步骤成功完成' if status['state'] == 'completed' else '当前步骤失败，后续步骤停止；已有产物保留')
                internal['finished_recorded'] = True
        elif job_status.get('state') in ['finished', 'failed']:
            public.update(state='failed', failureReason='执行入口退出，尚未开始步骤。请查看任务日志。', entry_log=tail(self.platform.job_folder(request_id)/job_id/'output.log'))
        resource = self.platform.resources.get(request_id, {})
        if resource.get('status') == 'closed' and public['state'] not in TERMINAL:
            public.update(state='interrupted', failureReason='GPU 已回收，任务中断；保留已有检查点，不自动重新申请或重跑')
        public['request_uuid'], public['job_uuid'] = request_id, job_id
        if internal.get('stop_confirmed') and public['state'] != 'completed':
            public.update(state='stopped',phase='任务已停止，已有产物保留')
            public.pop('failureReason',None)
            for step in public.get('step_records',[]):
                if step.get('state') == 'running': step['state'] = 'stopped'
        self.store.save(task)

    def stop_control(self, folder):
        target = folder/'run/stop-control.py'
        if not target.exists():
            shutil.copyfile(Path(__file__).with_name('stop_control.py'), target)
            target.chmod(0o400)
        return target

    def process_stop(self, task):
        internal, public = task['internal'], task['public']
        if not internal.get('stop_requested_at') or internal.get('stop_confirmed') or public['state'] in ['completed','cancelled']:
            return
        folder = self.store.root/'tasks'/task['id']
        request, job = internal.get('request_uuid'), internal.get('job_uuid')
        proof = read_json(folder/'run/stop-result.json',{})
        valid = (proof.get('task')==task['id'] and proof.get('digest')==task['digest'] and
                 proof.get('stop_at')==internal['stop_requested_at'] and proof.get('uid')==os.getuid() and
                 proof.get('request')==request and (proof.get('job')==job or
                 proof.get('mode')=='supervisor' and 'supervise' in internal.get('argv',[])))
        not_dispatched = not job and not internal.get('dispatch')
        allocation_closed = request and self.platform.resources.get(request,{}).get('status')=='closed'
        if (valid and proof.get('state')=='stopped') or not_dispatched or allocation_closed:
            Control(self.store).confirm_stop(task['id'],task['digest'])
            internal['stop_confirmed'] = True
            public.update(state='stopped',phase='任务已停止，已有产物保留')
            public.pop('failureReason',None)
            public['events'].append('已确认任务停止；不会自动重跑；停止任务不等于释放 GPU')
            for step in public.get('step_records',[]):
                if step.get('state') == 'running': step['state'] = 'stopped'
            self.store.save(task);return
        if valid and proof.get('state')=='unverified':
            public['phase'] = '停止状态待核查：'+redact(proof.get('error','未能确认所有任务进程退出'))
            self.store.save(task);return
        if 'supervise' in internal.get('argv',[]) and not internal.get('stop_dispatch'):
            # The new control layer observes the marker itself. A separate GPU
            # command is only a fallback if that layer does not confirm in time.
            started = internal.setdefault('stop_supervisor_wait_started',time.time())
            if time.time()-started<15:
                public.update(state='stopping',phase='已通知执行器停止，等待进程退出确认')
                self.store.save(task);return
        if internal.get('stop_dispatch'):
            if internal.get('stop_job_uuid'):
                stop_folder = self.platform.job_folder(request)/internal['stop_job_uuid']
                stop_status = read_json(stop_folder/'status.json',{})
                if stop_status.get('state') in ['finished','failed'] and not valid:
                    public['phase'] = '停止命令已退出但未获得有效确认，状态待核查'
                    public['stop_log'] = tail(stop_folder/'output.log')
                    self.store.save(task)
            if internal['stop_dispatch']=='submitting' and not internal.get('stop_job_uuid'):
                matches = [p.stem for p in self.platform.job_folder(request).glob('*.json') if read_json(p,{}).get('argv')==internal['stop_argv']]
                if len(matches)==1: internal.update(stop_job_uuid=matches[0],stop_dispatch='submitted')
                else: public['phase'] = '停止请求提交回执待核查，不会重复发送'
                self.store.save(task)
            return
        if not request or not job:
            public['phase'] = '正在核对原计算任务回执，停止请求已保存'
            self.store.save(task);return
        control = self.stop_control(folder)
        argv = ['/usr/bin/python3','-I',str(control),'stop',str(folder),request,job]
        internal.update(stop_dispatch='submitting',stop_argv=argv)
        public.update(state='stopping',phase='停止请求已发送，等待 GPU 确认进程退出')
        self.store.save(task)
        # Same allocation, a control-only command. No model or resource request.
        stopped_job = self.platform.submit_job(request,argv,task['doc']['project'])
        internal.update(stop_dispatch='submitted',stop_job_uuid=stopped_job)
        self.store.save(task)

    def dispatch(self, task, selection):
        if not task['internal'].get('approved_at') or task['internal'].get('dispatch'):
            return
        resource, devices = selection
        folder = self.store.root/'tasks'/task['id']
        self.remote('/api/worker/claim', {'id': task['id'], 'digest': task['digest'], 'revision': self.remote_revision})
        control = self.stop_control(folder)
        argv = ['/usr/bin/python3', '-I', str(control), 'supervise', str(folder)]
        internal = task['internal']
        internal.update(request_uuid=resource['id'], dispatch='submitting', argv=argv, dispatched_at=time.time(), gpu_uuids=devices)
        task['public'].update(state='dispatching', phase='等待 GPU 执行入口领取任务')
        atomic_json(folder/'run/approval.json', {'digest': task['digest'], 'approved_at': internal['approved_at'], 'gpu_uuids': devices})
        atomic_json(folder/'run/dispatch.json', {'task':task['id'],'digest':task['digest'],'request':resource['id'],'argv':argv})
        self.store.save(task)
        # A crash after the command writes a job is reconciled by exact argv.
        try:
            job = self.platform.submit_job(resource['id'], argv, task['doc']['project'])
        except BaseException:
            self.refresh_task(task)
            raise
        internal.update(job_uuid=job, dispatch='submitted')
        atomic_json(folder/'run/dispatch.json', {'task':task['id'],'digest':task['digest'],'request':resource['id'],'job':job,'argv':argv})
        task['public']['events'].append('复用可用 GPU，完整流程已提交；每一步成功后才进入下一步')
        self.store.save(task)

    def tick(self):
        for task in self.store.tasks():
            self.refresh_task(task)
        # Synchronize authorization and order before any platform operation.
        self.sync()
        for task in self.store.tasks():
            self.process_stop(task)
        tasks = self.store.tasks()
        active = [t for t in tasks if t['public']['state'] in ['starting', 'running', 'dispatching', 'execution_unknown', 'stopping']]
        pending = sorted([t for t in tasks if t['internal'].get('approved_at') and t['public']['state'] in ['queued', 'waiting_gpu', 'checking_resources']], key=lambda t: t['internal']['position'])
        self.platform.refresh(active=bool(active or pending))
        self.record_release_intents(tasks)
        if not pending:
            return
        task = pending[0]
        selection, reason = self.platform.select(task, active)
        if selection:
            self.dispatch(task, selection)
        else:
            task['public'].update(state='waiting_gpu', phase=reason)
            self.store.save(task)
            if not active:
                request_id = self.platform.request(task)
                if request_id:
                    task['public'].update(phase='GPU 申请已保存，等待平台就绪通知', request_uuid=request_id)
                    self.store.save(task)

    def record_release_intents(self, tasks):
        """Track the user's intent without pretending an unsupported release ran."""
        policy = self.store.metadata('resource_policy') or {}
        if not policy.get('release_when_queue_idle'):
            return
        # A failed/blocked submission may still be running. It must be reconciled
        # before any future release adapter can act on this intent.
        busy = any(t['internal'].get('approved_at') and (
            t['public']['state'] not in TERMINAL or
            t['internal'].get('dispatch') in ['submitting', 'unknown']
        ) for t in tasks)
        changed = False
        for resource in self.platform.resources.values():
            if not resource.get('owned_by_gpuq') or not resource.get('release_when_done') or resource['status'] in ['closed', 'failed']:
                continue
            intended = 'armed' if busy else 'pending_interface'
            if resource.get('release', {}).get('state') == intended:
                continue
            release = {'state': intended, 'at': now(), 'released': False,
                       'reason': '等待已启动的队列结束' if busy else '队列已结束；平台尚无成员主动释放接口，资源未确认释放'}
            resource['release'] = release
            atomic_json(self.store.root/'release-intents'/(resource['id']+'.json'), {'request': resource['id'], **release})
            changed = True
        if changed:
            self.platform.persist()

    def cycle(self):
        try:
            self.tick()
            self.error = None
        except QueueChanged:
            pass
        except Exception as error:
            message = redact(str(error))[:400]
            if message != self.error:
                print('Queue service: '+message, flush=True)
            self.error = message
            for task in self.store.tasks():
                if task['internal'].get('approved_at') and task['public']['state'] in ['queued', 'waiting_gpu', 'checking_resources']:
                    task['public']['phase'] = 'GPU 申请或状态核查未完成；已暂停新增申请：'+message
                    self.store.save(task)
        # tick publishes before platform I/O to read browser decisions. Publish
        # again afterwards so failures and recovered states reach the UI now.
        try:
            self.sync()
        except Exception as error:
            self.error = redact(str(error))[:400]
        atomic_json(self.store.root/'service-status.json', {'at': now(), 'error': self.error, 'pid': os.getpid()})

    def serve(self):
        lock = (self.store.root/'service.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        print('GPU queue service started; browser approval is required.', flush=True)
        while True:
            self.cycle()
            time.sleep(5)
