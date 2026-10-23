"""Personal Markflow adapter. No action is called until browser approval exists."""
import csv
import datetime as dt
import json
import math
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

PROBE_SCRIPT = '''import subprocess,json,time,socket
def query(fields,kind='gpu'):
 p=subprocess.run(['nvidia-smi','--query-'+kind+'='+fields,'--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=20)
 if p.returncode:raise RuntimeError('nvidia-smi query failed')
 return p.stdout.strip()
gpus=query('index,uuid,name,memory.total,memory.used,utilization.gpu,temperature.gpu')
at=time.time()
print('GPUQ_TELEMETRY='+json.dumps({'gpus':gpus,'apps':query('gpu_uuid,pid','compute-apps'),'at':at,'host':socket.gethostname()}))
'''

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
                if resource['status'] not in ['online', 'closed', 'failed']:
                    resource['status'] = 'ready'
                resource['ready_message'] = message.get('message_id')
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

    def refresh_probe(self, resource):
        if resource['status'] not in ['ready', 'online']:
            return
        probe = resource.get('probe')
        if probe:
            folder = self.job_folder(resource['id']) / probe['job']
            status = read_json(folder/'status.json', {})
            if status.get('state') == 'finished' and status.get('exit_code') == 0:
                output = (folder/'output.log').read_text(errors='replace')
                line = next((line for line in output.splitlines() if line.startswith('GPUQ_TELEMETRY=')), None)
                if not line:
                    raise PlatformError('GPU 检查已结束但没有有效遥测')
                payload = json.loads(line.split('=', 1)[1])
                gpus = []
                for row in csv.reader(payload['gpus'].splitlines(), skipinitialspace=True):
                    if len(row) not in [6, 7]:
                        raise PlatformError('GPU 遥测字段不完整')
                    temperature = row[6].strip() if len(row) == 7 else 'N/A'
                    gpus.append({'index': int(row[0]), 'uuid': row[1], 'name': row[2], 'total_mb': float(row[3]), 'used_mb': float(row[4]), 'utilization': float(row[5]), 'temperature_c': None if temperature in ['N/A', '[N/A]', 'Not Supported', '[Not Supported]'] else float(temperature)})
                apps = [row for row in csv.reader(payload['apps'].splitlines(), skipinitialspace=True) if len(row) == 2]
                stamp = float(payload.get('at', status.get('at', (folder/'output.log').stat().st_mtime)))
                if not math.isfinite(stamp) or stamp <= 0 or stamp > time.time()+5:
                    raise PlatformError('GPU 遥测采样时间无效')
                resource.update(status='online', telemetry={'gpus': gpus, 'apps': apps, 'at': stamp, 'host': payload.get('host', '')}, probe=None, probe_checked=time.time())
                resource.setdefault('samples', []).append({'at': stamp, 'utilization': max((g['utilization'] for g in gpus), default=100)})
                resource['samples'] = [sample for sample in resource['samples'] if stamp-sample['at'] < 420]
                return
            if status.get('state') in ['failed', 'finished']:
                resource.update(status='unknown', probe=None, error='GPU 只读检查失败，无法确认资源可用')
                return
            if time.time()-probe['at'] > 100:
                # Only remove a diagnostic that has not been claimed.
                specification = self.job_folder(resource['id'])/(probe['job']+'.json')
                if not status and specification.exists():
                    specification.unlink()
                resource.update(status='unknown', probe=None, error='GPU 检查超时；不会据此重复申请')
            return
        if time.time()-resource.get('probe_checked', 0) >= 30:
            job = self.submit_job(resource['id'], ['/usr/bin/python3', '-c', PROBE_SCRIPT], self.home)
            resource['probe'] = {'job': job, 'at': time.time()}
            self.persist()

    def refresh(self, active=False):
        self.discover()
        try:
            # Resource monitoring outlives compute jobs. These existing read-only
            # probes never request GPUs or authorize model execution.
            errors = []
            for resource in list(self.resources.values()):
                # A failed notification query must not prevent reading a probe
                # already completed in shared HOME, or skip other allocations.
                for refresh in (self.refresh_notice, self.refresh_probe):
                    try:
                        refresh(resource)
                    except (PlatformError, OSError, subprocess.SubprocessError) as error:
                        errors.append(error)
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
        unresolved = [r for r in self.resources.values() if r['status'] not in ['closed', 'failed']]
        required = task['doc']['resources']
        # A known smaller allocation may be insufficient. Unknown or busy usable
        # allocations must be reconciled rather than treated as absent.
        if any(r['status'] != 'online' or time.time()-r.get('telemetry', {}).get('at', 0)>90 or len([g for g in r.get('telemetry', {}).get('gpus', []) if g['total_mb'] >= memory_mb(required)+reserve_mb(g)]) >= required['gpus'] and r.get('type') == required['type'] for r in unresolved):
            return None
        if read_json(self.store.root/'tasks'/task['id']/'run/stop.json',{}).get('digest') == task['digest']:
            return None
        data = self.lark(['base', '+form-detail', '--share-token', FORM])
        if read_json(self.store.root/'tasks'/task['id']/'run/stop.json',{}).get('digest') == task['digest']:
            return None
        resource = task['doc']['resources']
        request_id = task['internal'].get('request_uuid') or str(uuid.uuid4())
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
        atomic_json(state_file, {'state': 'submitting', 'request': request_id, 'task': task['id'], 'created_at': now(), 'release_when_done': release_when_done, 'authorization': {'source': 'gpuq_browser_start', 'at': task['internal']['approved_at'], 'digest': task['digest']}})
        task['internal']['request_uuid'] = request_id
        self.store.save(task)
        self.resources[request_id] = {'id': request_id, 'status': 'pending', 'type': resource['type'], 'gpus': resource['gpus'], 'samples': [], 'owned_by_gpuq': True, 'release_when_done': release_when_done}
        self.persist()
        try:
            relative = str((folder/'request.json').relative_to(self.home))
            receipt = self.lark(['base', '+form-submit', '--share-token', FORM, '--json', '@'+relative, '--yes'], timeout=90)
            atomic_json(folder/'receipt.json', receipt)
            atomic_json(state_file, {**read_json(state_file), 'state': 'submitted', 'submitted_at': now()})
        except BaseException:
            atomic_json(state_file, {**read_json(state_file), 'state': 'submission_unknown', 'updated_at': now()})
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
            if resource['status'] != 'online' or time.time()-telemetry.get('at', 0) > 90 or resource.get('type') != required['type']:
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
            available = [g for g in telemetry.get('gpus', []) if g['uuid'] not in occupied and g['total_mb']-g['used_mb'] >= required_mb+reserve_mb(g, parallel=bool(active))]
            available.sort(key=lambda gpu: gpu['total_mb']-gpu['used_mb'], reverse=True)
            if len(available) >= required['gpus']:
                return (resource, [g['uuid'] for g in available[:required['gpus']]]), ''
        if any(r['status'] == 'online' and r.get('type') == required['type'] and time.time()-r.get('telemetry', {}).get('at', 0)<=90 for r in self.resources.values()):
            return None, 'GPU 已就绪；当前空闲显存或并行条件尚不满足任务要求'
        if any(r['status'] == 'pending' for r in self.resources.values()):
            return None, 'GPU 申请已提交，等待平台就绪通知'
        return None, '等待可复用 GPU；持续低占用且显存充足时最多并行两个任务'
