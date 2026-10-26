"""Model-independent NVIDIA samples; missing counters remain unknown."""
import csv
import math
import time

PROBE_SCRIPT = '''import subprocess,json,time,socket,sys
def query(fields,kind='gpu'):
 p=subprocess.run(['nvidia-smi','--query-'+kind+'='+fields,'--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=20)
 if p.returncode:raise RuntimeError('nvidia-smi query failed')
 return p.stdout.strip()
try:
 try:gpus=query('index,uuid,name,memory.total,memory.used,utilization.gpu,temperature.gpu')
 except RuntimeError:gpus=query('index,uuid,name,memory.total,memory.used,utilization.gpu')
 at=time.time()
 try:apps=query('gpu_uuid,pid','compute-apps');apps_known=True
 except RuntimeError:apps='';apps_known=False
except subprocess.TimeoutExpired:
 print('GPUQ_PROBE_TIMEOUT=1',flush=True)
 sys.exit(124)
print('GPUQ_TELEMETRY='+json.dumps({'gpus':gpus,'apps':apps,'apps_known':apps_known,'at':at,'host':socket.gethostname()}))
'''


def counter(value, maximum=None):
    value = value.strip()
    if value in ('N/A', '[N/A]', 'Not Supported', '[Not Supported]', ''):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0 or maximum is not None and number > maximum:
        raise ValueError('GPU 遥测数值无效')
    return number


def parse_sample(payload, fallback_at):
    gpus, seen = [], set()
    for row in csv.reader(payload['gpus'].splitlines(), skipinitialspace=True):
        if len(row) not in (6, 7):
            raise ValueError('GPU 遥测字段不完整')
        index, uid = int(row[0]), row[1].strip()
        if index < 0 or not uid or uid in seen:
            raise ValueError('GPU 遥测标识无效')
        seen.add(uid)
        total, used = counter(row[3]), counter(row[4])
        if total == 0 or total is not None and used is not None and used > total:
            raise ValueError('GPU 遥测显存无效')
        gpus.append(dict(index=index, uuid=uid, name=row[2].strip(), total_mb=total,
                         used_mb=used, utilization=counter(row[5], 100),
                         temperature_c=counter(row[6]) if len(row) == 7 else None))
    if not gpus:
        raise ValueError('GPU 检查没有返回任何显卡')
    apps = list(csv.reader(payload.get('apps', '').splitlines(), skipinitialspace=True))
    apps_known = payload.get('apps_known', True) is True and all(
        len(row) == 2 and row[0] in seen and row[1].strip().isdigit() for row in apps)
    stamp = float(payload.get('at', fallback_at))
    if not math.isfinite(stamp) or stamp <= 0 or stamp > time.time()+5:
        raise ValueError('GPU 遥测采样时间无效')
    return dict(gpus=gpus, apps=apps if apps_known else [], apps_known=apps_known,
                at=stamp, host=payload.get('host', ''))


def monitor_status(resource):
    if resource['status'] in ['closed', 'failed', 'pending']:
        state = resource['status']
    elif resource.get('probe_submission'):
        state = 'reconciling'
    elif resource.get('probe'):
        state = 'waiting' if resource['status'] == 'unknown' else 'sampling'
    elif resource.get('probe_retry_at', 0) > time.time():
        state = 'retry'
    else:
        state = 'monitoring'
    return dict(state=state, retry_at=resource.get('probe_retry_at'))
