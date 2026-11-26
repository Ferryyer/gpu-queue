from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import time
from .core import Store, HOME, DEFAULT_ROOT, SITE_URL, TERMINAL, atomic_json, read_json, canonical, now
from .platform import Markflow, PlatformError
from .feishu import FeishuAuthError
from .resources import published_resources

from .control import Control, QueueChanged

def redact(text):
    text = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', r'\1[redacted]', text)
    text = re.sub(
        r"""(?i)((?:api[_-]?key|(?:access|refresh)[_-]?token|device[_-]?code|password|secret)["']?\s*[=:]\s*)("[^"]*"|'[^']*'|[^\s,;]+)""",
        r'\1[redacted]', text)
    return re.sub(r'\bsk-[A-Za-z0-9_-]{15,}', '[redacted]', text)

def tail(path, limit=8000):
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size-limit))
        return redact(stream.read(limit).decode(errors='replace'))

class RunnerStatusError(ValueError):
    pass

def runner_status(path):
    try:
        status = read_json(path)
        if status is None and not path.exists():
            return None
        if not isinstance(status, dict) or not isinstance(status.get('state'), str):
            raise ValueError('执行状态必须是 JSON 对象')
        return status
    except (OSError, ValueError) as error:
        # Keep the corrupt file intact and distinguish it from a missing file.
        raise RunnerStatusError('任务执行状态文件不可读，状态待核查（'+type(error).__name__+'）') from error

class Service:
    def __init__(self, config, store=None, platform=None):
        self.config = config
        self.store = store or Store()
        self.platform = platform or Markflow(self.store, config)
        self.remote_revision = None
        self.error = None
        self.checked_at = None

    def remote(self, path, payload):
        control = Control(self.store)
        if path == '/api/worker/sync':
            return control.sync(payload['heartbeat'])
        if path == '/api/worker/claim':
            return control.claim(payload['id'], payload['digest'], payload['revision'])
        raise ValueError('Unknown internal queue operation')

    def sync(self):
        resources = []
        for resource in published_resources(self.platform.resources).values():
            resources.append({key: resource.get(key) for key in ['id', 'status', 'type', 'gpus', 'telemetry', 'error', 'release', 'monitor', 'recorded_phase']})
        response = self.remote('/api/worker/sync', {'heartbeat': {
            'service': 'online', 'error': self.error, 'resources': resources,
            'resource_policy': self.store.metadata('resource_policy'), 'updated_at': now(),
            'feishu_auth': self.store.metadata('feishu_auth'),
            'checked_at': self.checked_at,
            'last_success_at': self.store.metadata('queue_last_success_at'),
        }})
        self.remote_revision = response['revision']
        for remote in response['tasks']:
            local = self.store.get(remote['id'])
            if not local or local['digest'] != remote['digest']:
                continue
            previous = deepcopy(local)
            if remote.get('approved_at') and not local['internal'].get('approved_at'):
                local['internal']['approved_at'] = remote['approved_at']
                local['public']['approved_at'] = remote['approved_at']
                if local['public']['state'] == 'ready':
                    local['public']['state'] = 'queued'
                local['public']['events'].append('你在网页点击了开始，授权执行这一版完整流程')
            if remote.get('claimed_at'):
                local['internal']['claimed_at'] = remote['claimed_at']
            if remote.get('stopped_at'):
                local['internal']['stop_confirmed'] = True
            if (not local['internal'].get('dispatch')
                    and not local['internal'].get('job_uuid')
                    and not local['internal'].get('stop_confirmed')
                    and (remote.get('claimed_at') and local['public']['state'] not in TERMINAL - {'blocked'}
                         or remote['state'] == 'stopping')):
                local['internal']['dispatch'] = 'unknown'
                local['public'].update(state='blocked', failureReason='任务已被领取，正在核对计算投放记录')
            local['internal']['position'] = remote['position']
            if remote.get('stop_requested_at'):
                at = remote['stop_requested_at']
                if not local['internal'].get('stop_requested_at'):
                    local['public']['events'].append('你在网页请求停止任务；已有产物保留，后续步骤不再执行')
                if (local['internal'].get('stop_requested_at') != at or
                        not local['internal'].get('stop_confirmed') and remote['state'] not in ['completed', 'cancelled']):
                    atomic_json(self.store.root/'tasks'/local['id']/'run/stop.json', {'task':local['id'],'digest':local['digest'],'at':at})
                local['internal']['stop_requested_at'] = at
                if remote['state'] != 'completed':
                    phase = ('已移出队列' if remote['state']=='cancelled' else
                             '任务已停止，已有产物保留' if remote['state']=='stopped' else
                             local['internal'].get('stop_phase') or
                             (local['public'].get('phase') if local['public']['state']=='stopping' else None))
                    phase = phase or '正在确认任务进程退出；已有产物保留'
                    reason = local['public'].get('failureReason')
                    if (remote['state'] == 'stopping' and not local['internal'].get('stop_phase')
                            and reason and reason not in phase):
                        phase += '；'+reason
                    local['public'].update(state=remote['state'], phase=phase)
                    if remote['state'] == 'stopped':
                        local['public'].pop('failureReason', None)
                        for step in local['public'].get('step_records', []):
                            if step.get('state') == 'running': step['state'] = 'stopped'
            self.save_if_changed(local, previous)

    def save_if_changed(self, task, previous):
        if task != previous:
            self.store.save(task)

    def original_dispatch(self, task):
        """Recover only the version-bound original allocation and command."""
        internal = task['internal']
        request, argv = internal.get('request_uuid'), internal.get('argv')
        marker = read_json(self.store.root/'tasks'/task['id']/'run/dispatch.json', {})
        if not isinstance(marker, dict):
            return None, None
        if marker:
            # request_uuid is also saved while applying for a GPU. Until a
            # dispatch identity is persisted, the version-bound marker records
            # the allocation actually selected (which can be a reused GPU).
            dispatched = (argv or internal.get('job_uuid') or internal.get('dispatched_at') or
                          internal.get('dispatch') in {'submitting', 'submitted'})
            if (marker.get('task') != task['id'] or marker.get('digest') != task['digest'] or
                    dispatched and request and marker.get('request') != request or
                    argv and marker.get('argv') != argv):
                return None, None
            request, argv = marker.get('request'), argv or marker.get('argv')
        return request, argv

    def refresh_task(self, task):
        internal = task['internal']
        if internal.get('stop_requested_at') and not internal.get('stop_confirmed'):
            # A crash can leave the confirmation committed in controls before
            # the task snapshot records it. Recover it before any result I/O.
            with self.store.connect() as db:
                row = db.execute('SELECT controls.stopped_at FROM controls JOIN tasks ON tasks.id=controls.id '
                                 'WHERE tasks.id=? AND tasks.digest=? AND controls.stop_at=?',
                                 (task['id'], task['digest'], internal['stop_requested_at'])).fetchone()
            if row and row['stopped_at']:
                internal['stop_confirmed'] = True
        if not internal.get('stop_confirmed'):
            previous = deepcopy(task)
            try:
                return self._refresh_task(task)
            except RunnerStatusError as error:
                public = task['public']
                message = str(error)+'；不会自动重跑，原文件保留供排查'
                if public.get('result_refresh_error') != message:
                    public['events'].append(message)
                public.update(state='stopping' if internal.get('stop_requested_at') else 'execution_unknown',
                              failureReason=message, result_refresh_error=message)
                self.save_if_changed(task, previous)
                return
        # Late results are optional enrichment after a confirmed stop. Work on
        # a copy so malformed metadata or unreadable logs cannot partially
        # overwrite the saved result or stop other tasks from being scheduled.
        candidate = deepcopy(task)
        try:
            self._refresh_task(candidate)
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
            previous = deepcopy(task)
            public = task['public']
            message = '迟到结果读取失败，保留已确认停止；稍后重试：'+redact(type(error).__name__+': '+str(error))[:400]
            if public.get('result_refresh_error') != message:
                public['events'].append(message)
            public['result_refresh_error'] = message
            if public['state'] != 'completed':
                public.update(state='stopped', phase='任务已停止，已有产物保留')
            self.save_if_changed(task, previous)
        else:
            task.update(candidate)

    def _refresh_task(self, task):
        internal, public = task['internal'], task['public']
        previous = deepcopy(task)
        confirmed = internal.get('stop_confirmed')
        if confirmed and public['state'] == 'completed':
            return
        request_id, job_id = internal.get('request_uuid'), internal.get('job_uuid')
        recovering_job = not job_id
        if (confirmed or internal.get('dispatch') in ['submitting', 'unknown']) and not job_id:
            matches = []
            try:
                request_id, expected = self.original_dispatch(task)
                if request_id and not confirmed:
                    internal['request_uuid'] = request_id
                if request_id and expected:
                    if not confirmed:
                        internal['argv'] = expected
                    for file in self.platform.job_folder(request_id).glob('*.json'):
                        receipt = read_json(file, {})
                        if not isinstance(receipt, dict):
                            raise ValueError('Invalid compute receipt')
                        if receipt.get('argv') == expected:
                            matches.append(file.stem)
            except (OSError, ValueError, TypeError):
                matches = []
            if len(matches) == 1:
                job_id = matches[0]
                if not confirmed:
                    internal.update(request_uuid=request_id, job_uuid=job_id, dispatch='submitted')
                    public.update(state='dispatching', phase='已核对计算回执，等待执行状态')
            else:
                if confirmed:
                    # Late receipts may enrich results, but cannot undo the
                    # confirmed stop or rewrite the original dispatch record.
                    public.update(state='stopped', phase='任务已停止，已有产物保留')
                    public.pop('failureReason', None)
                    for step in public.get('step_records', []):
                        if step.get('state') == 'running': step['state'] = 'stopped'
                else:
                    internal['dispatch'] = 'unknown'
                    public.update(state='stopping' if internal.get('stop_requested_at') else 'blocked',
                                  failureReason='GPU 提交曾中断，无法唯一确认回执；已停止自动重试')
                self.save_if_changed(task, previous)
                return
        if not job_id:
            return
        folder = self.store.root/'tasks'/task['id']
        status = runner_status(folder/'run/status.json')
        try:
            job_status = read_json(self.platform.job_folder(request_id)/job_id/'status.json', {})
            if not isinstance(job_status, dict):
                raise ValueError('Invalid compute job status')
        except (OSError, ValueError):
            # An unreadable receipt is not evidence that execution has ended.
            if confirmed or recovering_job or internal.get('stop_requested_at'):
                raise
            job_status = {}
        resource = self.platform.resources.get(request_id, {})
        if job_status.get('state') in ['finished', 'failed'] or resource.get('status') == 'closed':
            # The runner may have finished after the first status snapshot.
            # Read again after observing exit before freezing a terminal task.
            status = runner_status(folder/'run/status.json')
        if status:
            public.update(state=status['state'], stage=status.get('stage', 0), step_records=status.get('steps', []), progress=None)
            if status['state'] == 'completed':
                public.pop('failureReason', None)
            if status.get('error'):
                public['failureReason'] = redact(status['error'])[:1200]
            if status.get('gpu_verified'):
                public['checks'][-1] = 'GPU 设备已核验'
            if status['state'] in ['starting', 'running'] and time.time()-status.get('updated_at', 0)>180:
                if job_status.get('state') in ['finished', 'failed']:
                    public.update(state='interrupted', phase='任务中断，已有产物和日志保留', failureReason='执行进程已退出，未自动重跑；已有产物和日志保留')
                else:
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
        elif public['state'] not in TERMINAL and time.time()-internal.get('dispatched_at', job_status.get('at', 0)) > 180:
            public.update(state='execution_unknown', failureReason='已投放计算，等待执行端回执核查')
        if resource.get('status') == 'closed' and public['state'] not in TERMINAL:
            public.update(state='interrupted', failureReason='GPU 已回收，任务中断；保留已有检查点，不自动重新申请或重跑')
        public['request_uuid'], public['job_uuid'] = request_id, job_id
        public['execution'] = {'instance_id': request_id, 'job_id': job_id,
                               'workspace': str(folder/'code'),
                               'host': (resource.get('telemetry') or {}).get('host')}

        if internal.get('stop_confirmed') and public['state'] != 'completed':
            public.update(state='stopped',phase='任务已停止，已有产物保留')
            public.pop('failureReason',None)
            for step in public.get('step_records',[]):
                if step.get('state') == 'running': step['state'] = 'stopped'
        if public.get('result_refresh_error') and public.get('failureReason') == public['result_refresh_error']:
            public.pop('failureReason', None)
        public.pop('result_refresh_error', None)
        if (public['state'] in ['completed', 'failed', 'interrupted', 'stopped'] and (
                (status or {}).get('state') in ['completed', 'failed']
                or job_status.get('state') in ['finished', 'failed']
                or resource.get('status') == 'closed' or internal.get('stop_confirmed'))):
            # Persist the check so old tentative terminal snapshots get one
            # reconciliation, while verified history stays idle after restart.
            internal['terminal_reconciled'] = True
        self.save_if_changed(task, previous)

    def stop_control(self, folder):
        target = folder/'run/stop-control.py'
        if not target.exists():
            shutil.copyfile(Path(__file__).with_name('stop_control.py'), target)
            target.chmod(0o400)
        return target

    def stop_pending(self, task, phase, previous):
        if task['internal'].get('stop_retry_consumed_at') is not None:
            phase += '；已用完一次自动重发机会'
        task['internal']['stop_phase'] = phase
        task['public'].update(state='stopping', phase=phase)
        self.save_if_changed(task, previous)

    def submit_stop(self, task, request):
        previous = deepcopy(task)
        internal = task['internal']
        try:
            job = self.platform.submit_job(request, internal['stop_argv'], internal.get('stop_cwd', task['doc']['project']))
        except Exception as error:
            # The shared platform error describes compute's no-retry policy.
            # Stop control has its own persisted, one-retry policy.
            internal['stop_submit_error'] = redact(str(error))[:400]
            phase = '停止请求提交回执待核查'
            if internal.get('stop_retry_consumed_at') is None:
                phase += '；等待满 60 秒后核对，满足条件时最多自动重发一次'
            self.stop_pending(task, phase, previous)
            raise PlatformError(task['public']['phase']) from error
        internal.pop('stop_submit_error', None)
        internal.update(stop_dispatch='submitted', stop_job_uuid=job)
        internal['stop_receipts'] = sorted(set(internal.get('stop_receipts', [])) | {job})
        self.stop_pending(task, '已核对停止命令回执，等待进程退出确认', previous)

    def process_stop(self, task):
        internal, public = task['internal'], task['public']
        if not internal.get('stop_requested_at') or internal.get('stop_confirmed') or public['state'] in ['completed','cancelled']:
            return
        previous = deepcopy(task)
        folder = self.store.root/'tasks'/task['id']
        request, job = internal.get('request_uuid'), internal.get('job_uuid')
        try:
            original_request, original_argv = self.original_dispatch(task)
        except (OSError, ValueError, TypeError):
            original_request, original_argv = None, None
        try:
            proof = read_json(folder/'run/stop-result.json',{})
            if not isinstance(proof, dict):
                proof = {}
        except (OSError, ValueError, TypeError):
            proof = {}
        supervisor = ['/usr/bin/python3', '-I', str(folder/'run/stop-control.py'), 'supervise', str(folder)]
        valid = (bool(request and job) and original_request == request and
                 proof.get('task')==task['id'] and proof.get('digest')==task['digest'] and
                 proof.get('stop_at')==internal['stop_requested_at'] and proof.get('uid')==os.getuid() and
                 proof.get('request')==request and (proof.get('job')==job or
                 proof.get('job') is None and proof.get('mode')=='supervisor' and original_argv == supervisor))
        allocation_closed = (request and original_request == request and
                             self.platform.resources.get(request,{}).get('status')=='closed')
        if (valid and proof.get('state')=='stopped') or allocation_closed:
            if job:
                # Matching stop proof is written after the process exits. A
                # natural completion since tick's first refresh takes priority.
                self.refresh_task(task)
                if public['state'] == 'completed':
                    return
            Control(self.store).confirm_stop(task['id'],task['digest'])
            internal['stop_confirmed'] = True
            internal['terminal_reconciled'] = True
            public.update(state='stopped',phase='任务已停止，已有产物保留')
            public.pop('failureReason',None)
            public['events'].append('已确认任务停止；不会自动重跑；停止任务不等于释放 GPU')
            for step in public.get('step_records',[]):
                if step.get('state') == 'running': step['state'] = 'stopped'
            self.save_if_changed(task, previous);return
        if valid and proof.get('state')=='unverified':
            self.stop_pending(task, '停止状态待核查：'+redact(proof.get('error','未能确认所有任务进程退出')), previous)
            return
        if not request or not job:
            reason = public.get('failureReason', '执行状态待核查')
            self.stop_pending(task, '停止状态待核查：正在核对原计算任务回执，停止请求已保存；'+reason, previous)
            return
        if original_request != request or internal.get('stop_request_uuid', request) != request:
            self.stop_pending(task, '原计算投放记录与任务版本不匹配，停止状态待核查', previous)
            return
        if 'supervise' in internal.get('argv',[]) and not internal.get('stop_dispatch'):
            # The new control layer observes the marker itself. A separate GPU
            # command is only a fallback if that layer does not confirm in time.
            started = internal.setdefault('stop_supervisor_wait_started',time.time())
            if time.time()-started<15:
                self.stop_pending(task, '已通知执行器停止，等待进程退出确认', previous)
                return
        if internal.get('stop_dispatch'):
            stop_request = internal.get('stop_request_uuid', request)
            bound = internal.get('stop_job_uuid')
            if internal['stop_dispatch'] == 'submitting' and not bound and 'stop_submitted_at' not in internal:
                # Legacy records get a full wait window from first takeover.
                internal['stop_submitted_at'] = time.time()
                self.store.save(task)
            seen = set(internal.get('stop_receipts', []))
            if bound:
                seen.add(bound)
            matches = []
            receipt_errors = {}
            try:
                # Continue even after binding: the other submission may arrive
                # later. glob may hide directory errors, which are not zero.
                for path in self.platform.job_folder(stop_request).iterdir():
                    if path.suffix != '.json':
                        continue
                    try:
                        receipt = json.loads(path.read_text())
                        if not isinstance(receipt, dict) or not isinstance(receipt.get('argv'), list):
                            raise ValueError('停止命令回执格式无效')
                    except (OSError, ValueError) as error:
                        receipt_errors[path.name] = redact(str(error))[:400]
                        continue
                    if receipt['argv'] == internal['stop_argv']:
                        matches.append(path.stem)
                        seen.add(path.stem)
            except OSError as error:
                receipt_errors['directory'] = redact(str(error))[:400]
            read_failed = bool(receipt_errors)
            if read_failed:
                internal['stop_receipt_error'] = canonical(receipt_errors)
            else:
                internal.pop('stop_receipt_error', None)
            # Receipt errors cannot hide independently readable job states.
            # Each job and log also has its own error boundary.
            states = internal.setdefault('stop_job_states', {})
            status_errors, log_errors = {}, {}
            for stop_job in sorted(seen):
                try:
                    stop_folder = self.platform.job_folder(stop_request)/stop_job
                    stop_status = read_json(stop_folder/'status.json', {})
                    if not isinstance(stop_status, dict):
                        raise ValueError('停止命令状态格式无效')
                    if stop_status.get('state'):
                        states[stop_job] = stop_status['state']
                except (OSError, ValueError) as error:
                    status_errors[stop_job] = redact(str(error))[:400]
            exited = [job for job in sorted(seen) if states.get(job) in ['finished', 'failed']]
            logs = internal.setdefault('stop_job_logs', {})
            for stop_job in exited:
                try:
                    logs[stop_job] = tail(self.platform.job_folder(stop_request)/stop_job/'output.log')
                except OSError as error:
                    log_errors[stop_job] = redact(str(error))[:400]
            readable_logs = [(job, logs[job]) for job in exited if job in logs]
            if readable_logs:
                public['stop_log'] = readable_logs[0][1] if len(readable_logs) == 1 else '\n\n'.join(job+':\n'+log for job, log in readable_logs)
            for key, errors in [('stop_status_errors', status_errors), ('stop_log_errors', log_errors)]:
                if errors:
                    internal[key] = errors
                else:
                    internal.pop(key, None)
            internal['stop_receipts'] = sorted(seen)
            if not read_failed and len(matches) == 1 and len(seen) == 1 and not bound:
                bound = matches[0]
                internal.update(stop_job_uuid=bound, stop_dispatch='submitted')
            if exited:
                phase = '停止命令已退出但未获得有效确认，状态待核查'
                if len(seen) > 1:
                    phase += '；停止请求提交回执无法唯一确认'
                if read_failed:
                    phase += '；停止请求提交回执读取失败'
            elif read_failed:
                phase = '停止请求提交回执读取失败，状态待核查'
            elif status_errors:
                phase = '停止作业状态读取失败，状态待核查'
            elif len(seen) > 1 or seen and not bound:
                phase = '停止请求提交回执无法唯一确认，状态待核查'
            elif bound:
                phase = '已核对停止命令回执，等待进程退出确认'
            elif internal['stop_dispatch'] != 'submitting':
                phase = '停止请求提交回执待核查'
            elif time.time()-internal['stop_submitted_at'] < 60:
                phase = '停止请求提交回执待核查，等待满 60 秒后再核对'
            elif internal.get('stop_retry_consumed_at') is not None:
                phase = '停止请求提交回执待核查'
            else:
                # Commit the budget and audit together before platform I/O.
                # A crash even before the call must never allow a third send.
                internal['stop_retry_consumed_at'] = time.time()
                phase = '停止请求已自动重发，提交回执及进程退出状态待核查；已用完一次自动重发机会'
                internal['stop_phase'] = phase
                public.update(state='stopping', phase=phase)
                with self.store.connect() as db:
                    db.execute('UPDATE tasks SET public=?, internal=? WHERE id=?',
                               (canonical(public), canonical(internal), task['id']))
                    db.execute('INSERT INTO queue_audit(task_id,action,at) VALUES (?,?,?)',
                               (task['id'], 'stop_retry:'+task['digest']+':'+internal['stop_requested_at'], now()))
                self.submit_stop(task, stop_request)
                return
            if status_errors and exited:
                phase += '；停止作业状态读取失败'
            if log_errors:
                phase += '；停止日志读取失败'
            self.stop_pending(task, phase, previous)
            return
        control = self.stop_control(folder)
        argv = ['/usr/bin/python3','-I',str(control),'stop',str(folder),request,job]
        internal.update(stop_dispatch='submitting', stop_argv=argv, stop_submitted_at=time.time(),
                        stop_request_uuid=request, stop_cwd=task['doc']['project'])
        self.stop_pending(task, '停止请求已发送，提交回执及进程退出状态待核查', previous)
        # Same allocation, a control-only command. No model or resource request.
        self.submit_stop(task, request)

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
        self.platform.begin_task_sampling(task)

    def tick(self):
        for task in self.store.tasks():
            internal, public = task['internal'], task['public']
            # blocked and ambiguous submissions still need receipt reconciliation.
            pending_stop = (internal.get('stop_requested_at') and not internal.get('stop_confirmed')
                            and public['state'] not in ['completed', 'cancelled'])
            legacy_terminal = (internal.get('job_uuid') and not internal.get('terminal_reconciled')
                               and public['state'] in ['failed', 'interrupted', 'stopped'])
            if (public['state'] not in TERMINAL or public['state'] == 'blocked'
                    or internal.get('dispatch') in ['submitting', 'unknown'] or pending_stop or legacy_terminal):
                self.refresh_task(task)
        # Synchronize authorization and order before any platform operation.
        self.sync()
        for task in self.store.tasks():
            self.process_stop(task)
        tasks = self.store.tasks()
        active = [t for t in tasks if not t['internal'].get('stop_confirmed') and (
                  t['public']['state'] in ['starting', 'running', 'dispatching', 'execution_unknown', 'stopping', 'blocked']
                  or t['internal'].get('dispatch') in ['submitting', 'unknown'])]
        pending = sorted([t for t in tasks if t['internal'].get('approved_at')
                          and not t['internal'].get('dispatch') and not t['internal'].get('job_uuid')
                          and t['public']['state'] in ['queued', 'waiting_gpu', 'checking_resources']], key=lambda t: t['internal']['position'])
        self.platform.refresh(active=bool(active or pending))
        self.record_release_intents(tasks)
        if not pending:
            return
        task = pending[0]
        selection, reason = self.platform.select(task, active)
        if selection:
            self.dispatch(task, selection)
        else:
            previous = deepcopy(task)
            task['public'].update(state='waiting_gpu', phase=reason)
            self.save_if_changed(task, previous)
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
            t['internal'].get('dispatch') in ['submitting', 'unknown'] and not t['internal'].get('stop_confirmed')
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
            self.store.metadata('queue_last_success_at', now())
        except QueueChanged:
            pass
        except Exception as error:
            message = redact(str(error))[:400]
            if isinstance(error, FeishuAuthError):
                if self.platform.auth.get('code') != error.code:
                    self.platform.record_auth(error)
                message = '等待飞书本人授权，尚未投放计算。'+str(error)
            if message != self.error:
                print('Queue service: '+message, flush=True)
            self.error = message
            for task in self.store.tasks():
                if task['internal'].get('approved_at') and task['public']['state'] in ['queued', 'waiting_gpu', 'checking_resources']:
                    previous = deepcopy(task)
                    task['public']['phase'] = message if isinstance(error, FeishuAuthError) else 'GPU 申请或状态核查未完成；已暂停新增申请：'+message
                    self.save_if_changed(task, previous)
        # tick publishes before platform I/O to read browser decisions. Publish
        # again afterwards so failures and recovered states reach the UI now.
        self.checked_at = now()
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
