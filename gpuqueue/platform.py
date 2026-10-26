"""Personal Markflow adapter. No action is called until browser approval exists."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from .core import HOME, atomic_json, read_json, now
from .serverbox import publish as publish_serverbox

FORM = 'shrcn3qH6A3KPzzS07UzvgAUAkh'
TRUSTED_SENDER = 'cli_aa59fbf9c878dd0b'

def memory_mb(resources):
    # Manifests use decimal GB; nvidia-smi reports binary MiB.
    return (resources['memory_gb'] or 0) * 1_000_000_000 / (1024 * 1024)

def reserve_mb(gpu, parallel=False):
    # Serial tasks need a fixed driver/runtime reserve. The larger sharing
    # margin applies only when admitting another task onto an occupied GPU.
    return max(2048, gpu['total_mb'] * .1) if parallel else 2048

from .telemetry import PROBE_SCRIPT, parse_sample

class PlatformError(RuntimeError):
    pass

class Markflow:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.home = Path(config.get('home', HOME))
        self.resources = store.metadata('resources') or {}

    def run(self, argv, timeout=40, cwd=None):
        result = subprocess.run(argv, cwd=cwd or self.home, capture_output=True, text=True, timeout=timeout)
        return result

    def lark(self, args, timeout=45):
        result = self.run([self.config.get('lark_cli', 'lark-cli'), '--profile', '众解深算', *args, '--as', 'user'], timeout=timeout)
        try:
            data = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        except (ValueError, TypeError):
            raise PlatformError('飞书返回无法解析；请核查本人 CLI 登录和网络')
        if result.returncode != 0 or data.get('ok') is not True:
            error = data.get('error', {})
            raise PlatformError('飞书操作未成功：'+str(error.get('subtype', error.get('type', 'unknown'))))
        return data.get('data', {})

    def persist(self):
        self.store.metadata('resources', self.resources)

    @staticmethod
    def probe_timed_out(resource):
        # The error prefix recognizes timeout evidence written before this
        # policy existed. Unknown states and notification failures do not count.
        return resource.get('status') == 'unknown' and bool(
            resource.get('probe_timeout') or
            resource.get('error', '').startswith('GPU 检查超时'))

    def replacement_candidates(self, task):
        internal = task['internal']
        if not (self.store.metadata('resource_policy') or {}).get('replace_timed_out_gpu'):
            return []
        if not internal.get('approved_at') or internal.get('timeout_replacement') or internal.get('job_uuid') or internal.get('dispatch') in ['submitting', 'submitted', 'unknown']:
            return []
        return [r for r in self.resources.values() if self.probe_timed_out(r)
                and r.get('recorded_phase') not in ['submitting', 'submission_unknown']
                and (r.get('ready_message') or r.get('ready_notice_consumed') or r.get('telemetry'))]

    def discover(self):
        base = self.home / '.local/state/markflow-gpu-requests'
        for folder in sorted(base.iterdir() if base.exists() else []):
            try:
                request_id = str(uuid.UUID(folder.name))
                document = read_json(folder/'request.json', {})
                local = read_json(folder/'state.json', {})
                fields = document.get('fields', {})
                if not fields or fields.get('服务器用户名') != self.config['username']:
                    continue
                initial = 'pending' if local.get('state') in ['submitted', 'submitting', 'queued', 'submission_unknown'] else 'unknown'
                resource = self.resources.setdefault(request_id, {'id': request_id, 'status': initial, 'samples': []})
                resource.update(type=fields.get('资源类型'), gpus=fields.get('卡数'), purpose=fields.get('用途', '')[:180])
                if local.get('state') in ['closed', 'failed', 'rejected', 'cancelled']:
                    resource['status'] = 'closed' if local.get('state') == 'closed' else 'failed'
                # A submission receipt is historical, not evidence that a
                # previously online allocation is applying again after failure.
                resource['recorded_phase'] = local.get('state', 'unknown')
            except (ValueError, OSError):
                continue
        self.persist()

    def refresh_notice(self, resource):
        if resource['status'] in ['closed', 'failed'] or time.time() - resource.get('notice_checked', 0) < 60:
            return
        resource['notice_checked'] = time.time()
        data = self.lark(['im', '+messages-search', '--query', resource['id'], '--no-reactions'])
        messages = data.get('messages', [])
        for message in reversed(messages):
            if message.get('sender', {}).get('id') != TRUSTED_SENDER or message.get('deleted'):
                continue
            content = message.get('content', '')
            if not isinstance(content, str) or resource['id'] not in content:
                continue
            if not re.search(r'申请[：:\s]+'+re.escape(resource['id']), content):
                continue
            # The policy footer also contains "回收"; classify the title only.
            title = content.splitlines()[0].strip()
            if title.startswith('GPU已启动并通过成员权限与共享盘检查'):
                # Search returns historical notices on every poll. Once a ready
                # notice has been consumed, it cannot undo a failed/timed-out
                # probe and enqueue more work on an unresponsive allocation.
                if resource.get('ready_notice_consumed') or resource.get('ready_message'):
                    continue
                if resource['status'] not in ['online', 'closed', 'failed']:
                    resource['status'] = 'ready'
                resource['ready_message'] = message.get('message_id')
                resource['ready_notice_consumed'] = True
            elif re.match(r'^GPU.*(已回收|已关闭|已终止)', title):
                resource['status'] = 'closed'
            elif re.match(r'^GPU.*(申请失败|启动失败|申请被拒)', title):
                resource['status'] = 'failed'

    def job_folder(self, request_id):
        return self.home/'.local/state/markflow-gpu'/request_id/'jobs'

    def submit_job(self, request_id, argv, cwd):
        result = self.run([self.config.get('mf_gpu', '/usr/local/bin/mf-gpu'), 'submit', '--cwd', str(cwd), request_id, '--', *argv])
        if result.returncode:
            raise PlatformError('GPU 任务提交结果不明，已停止自动重试')
        try:
            value = json.loads(result.stdout)
            uuid.UUID(value['job'])
        except (ValueError, KeyError):
            raise PlatformError('GPU 任务回执不完整，已停止自动重试')
        return value['job']

    def archive_finished_probes(self, resource):
        # mf-gpu polls only the first 100 specifications. Completed probes must
        # leave that input window so a long-lived allocation keeps sampling.
        folder = self.job_folder(resource['id'])
        current = (resource.get('probe') or {}).get('job')
        for specification in folder.glob('*.json'):
            if specification.stem == current or specification.is_symlink():
                continue
            try:
                argv = read_json(specification, {}).get('argv', [])
                if argv == (resource.get('probe_submission') or {}).get('argv'):
                    continue
                own = (isinstance(argv, list) and len(argv) == 3 and isinstance(argv[2], str) and argv[:2] == ['/usr/bin/python3', '-c'] and
                       (argv[2].startswith(PROBE_SCRIPT+'\n# gpuq-probe ') or
                        hashlib.sha256(argv[2].encode()).hexdigest() == '3fa8d256a164cca527e5588ac1cb38c23eaffdc806cc51452ef341731221f9e9'))
                status = read_json(folder/specification.stem/'status.json', {})
                if not own or status.get('state') not in ['finished', 'failed']:
                    continue
                archive = folder/'.gpuq-probe-history'
                archive.mkdir(exist_ok=True, mode=0o700)
                target = archive/specification.name
                if not target.exists():
                    specification.rename(target)
            except (ValueError, TypeError, OSError):
                continue  # Keep the original receipt and try again next cycle.

    def probe_failure(self, resource, message, timed_out=False):
        was_timeout = self.probe_timed_out(resource)
        failures = resource.get('probe_failures', 0)+1
        resource.update(status='unknown', error=message, probe_failures=failures,
                        probe_retry_at=time.time()+min(300, 30*2**min(failures-1, 4)))
        if timed_out or was_timeout:
            resource.setdefault('probe_timeout', {'at': now(), 'job': (resource.get('probe') or {}).get('job')})

    def refresh_probe(self, resource):
        if resource['status'] in ['pending', 'closed', 'failed']:
            return
        # Retry only known allocations, never ambiguous application receipts.
        if resource['status'] == 'unknown' and not (resource.get('telemetry') or
                resource.get('ready_message') or resource.get('ready_notice_consumed') or resource.get('probe') or resource.get('probe_submission')):
            return
        self.archive_finished_probes(resource)
        submission = resource.get('probe_submission')
        if submission:
            for specification in self.job_folder(resource['id']).glob('*.json'):
                if read_json(specification, {}).get('argv') == submission['argv']:
                    resource['probe'] = {'job': specification.stem, 'at': submission['at']}
                    resource.pop('probe_submission', None)
                    break
            if resource.get('probe_submission'):
                return  # Unknown submit outcome: reconcile, never duplicate it.
        probe = resource.get('probe')
        if probe:
            folder = self.job_folder(resource['id']) / probe['job']
            status = read_json(folder/'status.json', {})
            if status.get('state') == 'finished' and status.get('exit_code') == 0:
                try:
                    output = (folder/'output.log').read_text(errors='replace')
                    line = next((line for line in output.splitlines() if line.startswith('GPUQ_TELEMETRY=')), None)
                    if not line:
                        raise ValueError('GPU 检查已结束但没有有效遥测')
                    payload = json.loads(line.split('=', 1)[1])
                    telemetry = parse_sample(payload, (folder/'output.log').stat().st_mtime)
                    if telemetry['at'] <= resource.get('telemetry', {}).get('at', 0):
                        raise ValueError('GPU 遥测采样时间未前进')
                except (ValueError, KeyError, TypeError, OSError) as error:
                    self.probe_failure(resource, 'GPU 遥测无效：'+str(error))
                    resource['probe'] = None
                    return
                previous = {g['uuid'] for g in resource.get('telemetry', {}).get('gpus', [])}
                if previous != {g['uuid'] for g in telemetry['gpus']}:
                    resource['samples'] = []
                resource.update(status='online', telemetry=telemetry, probe=None,
                                probe_checked=time.time(), probe_failures=0)
                for key in ['error', 'probe_timeout', 'probe_retry_at']:
                    resource.pop(key, None)
                utilization = max((g['utilization'] if g['utilization'] is not None else 100
                                   for g in telemetry['gpus']), default=100)
                resource.setdefault('samples', []).append({'at': telemetry['at'], 'utilization': utilization})
                resource['samples'] = [s for s in resource['samples'] if telemetry['at']-s['at'] < 420]
                return
            if status.get('state') in ['failed', 'finished']:
                output = folder/'output.log'
                timed_out = (status.get('exit_code') == 124 and output.is_file() and
                             'GPUQ_PROBE_TIMEOUT=1' in output.read_text(errors='replace').splitlines())
                self.probe_failure(resource, 'GPU 检查超时；旧实例是否回收尚未确认' if timed_out
                                   else 'GPU 只读检查失败，稍后重试', timed_out)
                resource['probe'] = None
                return
            if time.time()-probe['at'] > 100 and resource['status'] != 'unknown':
                # Keep the receipt: a slow or disconnected worker can complete
                # it later. Never queue duplicate probes behind an unclaimed one.
                self.probe_failure(resource, 'GPU 检查超时；旧实例是否回收尚未确认', True)
            return
        if time.time() < resource.get('probe_retry_at', 0):
            return
        if time.time()-resource.get('probe_checked', 0) >= 30:
            argv = ['/usr/bin/python3', '-c', PROBE_SCRIPT+'\n# gpuq-probe '+str(uuid.uuid4())]
            resource['probe_submission'] = {'argv': argv, 'at': time.time()}
            self.persist()
            try:
                job = self.submit_job(resource['id'], argv, self.home)
            except (PlatformError, OSError, subprocess.SubprocessError) as error:
                if isinstance(error, OSError):
                    resource.pop('probe_submission', None)  # Child never started.
                self.probe_failure(resource, 'GPU 只读检查暂不可用：'+str(error))
                self.persist()
                raise
            resource['probe'] = {'job': job, 'at': time.time()}
            resource.pop('probe_submission', None)
            self.persist()

    def refresh(self, active=False):
        self.discover()
        try:
            # Resource monitoring outlives compute jobs. These existing read-only
            # probes never request GPUs or authorize model execution.
            errors = []
            replaceable = set()
            for task in self.store.tasks():
                replaceable.update(r['id'] for r in self.replacement_candidates(task))
                replaceable.update(task['internal'].get('timeout_replacement', {}).get('prior_requests', []))
            def record_error(resource, error, notice=False):
                if resource['id'] in replaceable and self.probe_timed_out(resource):
                    # Monitoring an old timed-out allocation must not veto an
                    # already authorized replacement or its newer allocation.
                    resource['notice_error' if notice else 'error'] = str(error)[:400]
                else:
                    errors.append(error)
            # Collect all outstanding receipts before potentially slow notice I/O.
            for resource in list(self.resources.values()):
                if resource.get('probe'):
                    try:
                        self.refresh_probe(resource)
                    except (PlatformError, OSError, subprocess.SubprocessError, ValueError) as error:
                        record_error(resource, error)
            for resource in list(self.resources.values()):
                # A failed notification query must not prevent reading a probe
                # already completed in shared HOME, or skip other allocations.
                for refresh in (self.refresh_notice, self.refresh_probe):
                    try:
                        refresh(resource)
                    except (PlatformError, OSError, subprocess.SubprocessError, ValueError) as error:
                        record_error(resource, error, notice=refresh == self.refresh_notice)
            if errors:
                # Keep the scheduler fail-closed while publishing any real
                # samples recovered above; never refresh their GPU timestamp.
                raise errors[0]
        finally:
            self.persist()
            publish_serverbox(self.resources, self.home)

    def request(self, task):
        if not task['internal'].get('approved_at'):
            raise PlatformError('任务未在网页启动')
        if task['internal'].get('job_uuid') or task['internal'].get('dispatch') in ['submitting', 'submitted', 'unknown']:
            return None
        replacements = self.replacement_candidates(task)
        replacement_ids = [r['id'] for r in replacements]
        unresolved = [r for r in self.resources.values() if r['status'] not in ['closed', 'failed'] and r.get('id') not in replacement_ids]
        required = task['doc']['resources']
        # A known smaller allocation may be insufficient. Unknown or busy usable
        # allocations must be reconciled rather than treated as absent.
        if any(r['status'] != 'online' or time.time()-r.get('telemetry', {}).get('at', 0)>90 or len([g for g in r.get('telemetry', {}).get('gpus', []) if g.get('total_mb') is not None and g['total_mb'] >= memory_mb(required)+reserve_mb(g)]) >= required['gpus'] and r.get('type') == required['type'] for r in unresolved):
            return None
        if read_json(self.store.root/'tasks'/task['id']/'run/stop.json',{}).get('digest') == task['digest']:
            return None
        data = self.lark(['base', '+form-detail', '--share-token', FORM])
        if read_json(self.store.root/'tasks'/task['id']/'run/stop.json',{}).get('digest') == task['digest']:
            return None
        resource = task['doc']['resources']
        prior_request = task['internal'].get('request_uuid')
        request_id = prior_request if prior_request and prior_request not in replacement_ids else str(uuid.uuid4())
        fields = {'申请标识': request_id, '服务器用户名': self.config['username'], '用途': task['doc']['title']+'；'+task['doc']['description'], '资源类型': resource['type'], '卡数': resource['gpus'], '预计小时': resource['estimated_hours'], '工作目录': task['doc']['project'], '规则确认': '已阅读并同意'}
        questions = data.get('questions', [])
        for question in questions:
            title = question['title']
            if question.get('required') and title not in fields or question.get('filter'):
                raise PlatformError('申请表结构有变化，需更新适配器后再申请')
            if title in fields and question.get('options') and fields[title] not in [o['name'] for o in question['options']]:
                raise PlatformError('申请表选项有变化，已停止申请')
        folder = self.home/'.local/state/markflow-gpu-requests'/request_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        state_file = folder/'state.json'
        previous = read_json(state_file, {})
        if previous.get('state'):
            task['internal']['request_uuid'] = request_id
            self.store.save(task)
            # Reusing a historical receipt is not a new/pending application.
            # Keep the admission failure reason instead of saying "等待就绪".
            return None
        atomic_json(folder/'request.json', {'fields': fields})
        release_when_done = bool((self.store.metadata('resource_policy') or {}).get('release_when_queue_idle'))
        replacement = {'prior_requests': replacement_ids, 'request': request_id, 'at': now(), 'reason': '旧 GPU 只读探测超时，按用户偏好补申请一次'} if replacement_ids else None
        atomic_json(state_file, {'state': 'submitting', 'request': request_id, 'task': task['id'], 'created_at': now(), 'release_when_done': release_when_done, 'authorization': {'source': 'gpuq_browser_start', 'at': task['internal']['approved_at'], 'digest': task['digest']}, 'timeout_replacement': replacement})
        task['internal']['request_uuid'] = request_id
        task['public']['request_uuid'] = request_id
        if replacement:
            task['internal']['timeout_replacement'] = replacement
            task['public']['events'].append(replacement['reason']+'；不代表旧实例已回收')
        self.store.save(task)
        self.resources[request_id] = {'id': request_id, 'status': 'pending', 'recorded_phase': 'submitting', 'type': resource['type'], 'gpus': resource['gpus'], 'samples': [], 'owned_by_gpuq': True, 'release_when_done': release_when_done}
        self.persist()
        try:
            relative = str((folder/'request.json').relative_to(self.home))
            receipt = self.lark(['base', '+form-submit', '--share-token', FORM, '--json', '@'+relative, '--yes'], timeout=90)
            atomic_json(folder/'receipt.json', receipt)
            atomic_json(state_file, {**read_json(state_file), 'state': 'submitted', 'submitted_at': now()})
            self.resources[request_id]['recorded_phase'] = 'submitted'
            self.persist()
        except BaseException:
            atomic_json(state_file, {**read_json(state_file), 'state': 'submission_unknown', 'updated_at': now()})
            self.resources[request_id]['recorded_phase'] = 'submission_unknown'
            self.persist()
            raise
        return request_id

    def select(self, task, active):
        required = task['doc']['resources']
        if any(t['public']['state'] in ['execution_unknown', 'stopping'] for t in active):
            return None, '原任务执行状态待核查，暂不增加并行'
        if active and (len(active) >= 2 or required['memory_gb'] is None or any(t['doc']['resources']['memory_gb'] is None for t in active)):
            return None, '默认顺序执行；未满足安全并行条件'
        for resource in self.resources.values():
            telemetry = resource.get('telemetry', {})
            if resource['status'] != 'online' or time.time()-telemetry.get('at', 0) > 90 or resource.get('type') != required['type'] or telemetry.get('apps_known') is False:
                continue
            if active:
                samples = [s for s in resource.get('samples', []) if time.time()-s['at'] < 330]
                if len(samples) < 5 or samples[-1]['at']-samples[0]['at'] < 270 or any(s['utilization'] >= 30 for s in samples):
                    continue
                if any(samples[i+1]['at']-samples[i]['at'] > 90 for i in range(len(samples)-1)):
                    continue
                if time.time()-max(t['internal'].get('dispatched_at', time.time()) for t in active) < 300:
                    continue
            managed_pids = set()
            for running in active:
                status = read_json(self.store.root/'tasks'/running['id']/'run/status.json', {})
                managed_pids.update(str(s['pid']) for s in status.get('steps', []) if s.get('state') == 'running' and s.get('pid'))
            occupied = {row[0] for row in telemetry.get('apps', []) if row[1] not in managed_pids}
            required_mb = memory_mb(required)
            available = [g for g in telemetry.get('gpus', []) if g.get('total_mb') is not None and g.get('used_mb') is not None and g['uuid'] not in occupied and g['total_mb']-g['used_mb'] >= required_mb+reserve_mb(g, parallel=bool(active))]
            available.sort(key=lambda gpu: gpu['total_mb']-gpu['used_mb'], reverse=True)
            if len(available) >= required['gpus']:
                return (resource, [g['uuid'] for g in available[:required['gpus']]]), ''
        if any(r['status'] == 'online' and r.get('type') == required['type'] and time.time()-r.get('telemetry', {}).get('at', 0)<=90 for r in self.resources.values()):
            return None, 'GPU 已就绪；当前空闲显存或并行条件尚不满足任务要求'
        replaceable = {r['id'] for r in self.replacement_candidates(task)}
        for resource in self.resources.values():
            if resource['status'] in ['closed', 'failed']:
                continue
            if resource['id'] in replaceable:
                continue
            request_id = resource['id']
            if resource.get('recorded_phase') in ['submitting', 'submission_unknown']:
                return None, f'申请 {request_id} 的提交回执待核查；已暂停新增申请，避免重复提交'
            if resource['status'] == 'pending':
                return None, f'已有 GPU 申请 {request_id} 等待平台就绪通知；未新增申请'
            if task['internal'].get('timeout_replacement') and self.probe_timed_out(resource):
                continue
            return None, f'旧申请 {request_id} 的可用状态待核查；已暂停新增申请。'+resource.get('error', '等待有效 GPU 探测回执')
        if task['internal'].get('timeout_replacement'):
            return None, '本任务已补申请一次；等待新申请回执或核查新资源，不再自动补申请'
        if replaceable:
            return None, '旧 GPU 查询超时；将按已保存偏好为本任务补申请一次，旧实例未确认回收'
        return None, '等待可复用 GPU；持续低占用且显存充足时最多并行两个任务'
