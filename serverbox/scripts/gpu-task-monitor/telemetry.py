#!/usr/bin/env python3
"""Read-only GPU-task sampler and freshness-checked ServerBox XML bridge."""
import argparse
import csv
import fcntl
import io
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path.home() / '.local/state/serverbox-gpu'
FIELDS = 'index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu'


def number(raw):
    if raw.strip() in ('N/A', '[N/A]', 'Not Supported', '[Not Supported]'):
        return None
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Invalid GPU measurement')
    return int(value)


def parse_csv(raw):
    result = []
    for row in csv.reader(io.StringIO(raw)):
        if not row:
            continue
        if len(row) != 7:
            raise ValueError('Unexpected NVIDIA query format')
        index, gpu_uuid, name, load, used, total, temperature = map(str.strip, row)
        result.append(dict(index=int(index), uuid=gpu_uuid, name=name,
                           utilization_gpu_pct=number(load), memory_used_mib=number(used),
                           memory_total_mib=number(total), temperature_c=number(temperature)))
    if not result:
        raise ValueError('No GPU returned by NVIDIA')
    return result


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    os.replace(temp, path)


def latest(root=ROOT):
    registry = root / 'registry.json'
    if registry.exists():
        # Queue lifecycle is authoritative once enabled. Never resurrect a
        # historical standalone sample after closure or a corrupt registry.
        try:
            value = json.loads(registry.read_text())
            if value.get('schema') != 1 or value.get('source') != 'gpuq':
                return None
            records = []
            for item in value['resources']:
                stamp = float(item.get('collected_at', 0))
                if not math.isfinite(stamp) or stamp < 0:
                    raise ValueError('Invalid registry timestamp')
                for gpu in item['gpus']:
                    if not isinstance(gpu['name'], str) or not isinstance(gpu['uuid'], str):
                        raise ValueError('Invalid GPU identity')
                    for key in ('utilization_gpu_pct', 'memory_used_mib', 'memory_total_mib', 'temperature_c'):
                        number = gpu[key]
                        if number is not None and (type(number) not in (int, float) or
                                                   not math.isfinite(number) or number < 0):
                            raise ValueError('Invalid GPU measurement')
                state = 'ok' if item['status'] == 'online' else item['status']
                records.append(dict(item, schema=1, source='gpuq', state=state,
                                    collected_at=stamp))
            return max(records, key=lambda x: (fresh(x), x['state'] not in ('closed', 'failed'),
                                               x['collected_at']), default=None)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None
    records = []
    for path in root.glob('*/latest.json'):
        try:
            data = json.loads(path.read_text())
            if data.get('schema') == 1 and isinstance(data.get('collected_at'), (int, float)):
                records.append(data)
        except (OSError, ValueError, TypeError):
            continue
    return max(records, key=lambda x: x['collected_at'], default=None)


def fresh(data, now=None, max_age=None):
    if not data or data.get('state') != 'ok' or not data.get('gpus'):
        return False
    if max_age is None:
        max_age = 90 if data.get('source') == 'gpuq' else 20
    age = (time.time() if now is None else now) - data['collected_at']
    return math.isfinite(age) and -5 <= age <= max_age


def status_text(data, now=None):
    if not data:
        return 'GPU：等待实例采集（暂无有效数据）'
    labels = dict(pending='申请中', ready='实例就绪，等待采样', unknown='连接待核查',
                  closed='已销毁或回收（平台已确认）', failed='申请或启动失败')
    retry_labels = dict(retry='查询断开，自动重连中', waiting='查询超时，自动核查中',
                        reconciling='正在核对原查询回执', sampling='正在重新采样')
    if fresh(data, now=now):
        state = '实时'
    elif data['state'] in ('closed', 'failed'):
        state = labels[data['state']]
    else:
        state = retry_labels.get((data.get('monitor') or {}).get('state'),
                                 labels.get(data['state'], '已停止或数据过期'))
    release = ' · 待释放，尚未确认销毁' if data.get('release_pending') else ''
    request = f' · GPU任务 {data["request"][:8]}'
    if not data.get('collected_at'):
        return f'GPU：{state}{release}{request}'
    collected = datetime.fromtimestamp(data['collected_at'], ZoneInfo('Asia/Shanghai'))
    return f'GPU：{state}{release} · 采集于 {collected:%m-%d %H:%M:%S} 北京时间{request}'


def as_xml(data):
    log = ET.Element('nvidia_smi_log')
    ET.SubElement(log, 'timestamp').text = datetime.fromtimestamp(
        data['collected_at'], ZoneInfo('Asia/Shanghai')).isoformat()
    for item in data['gpus']:
        gpu = ET.SubElement(log, 'gpu', id=item['uuid'])
        ET.SubElement(gpu, 'product_name').text = item['name'] + ' [GPU task]'
        temp = ET.SubElement(gpu, 'temperature')
        value = item['temperature_c']
        ET.SubElement(temp, 'gpu_temp').text = 'N/A' if value is None else f'{value} C'
        usage = ET.SubElement(gpu, 'utilization')
        value = item['utilization_gpu_pct']
        ET.SubElement(usage, 'gpu_util').text = 'N/A' if value is None else f'{value} %'
        memory = ET.SubElement(gpu, 'fb_memory_usage')
        for tag, key in [('used', 'memory_used_mib'), ('total', 'memory_total_mib')]:
            value = item[key]
            ET.SubElement(memory, tag).text = 'N/A' if value is None else f'{value} MiB'
    return ET.tostring(log, encoding='unicode')


def collect(request, seconds, interval, root=ROOT):
    folder = root / str(uuid.UUID(request))
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (folder / 'collector.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('A collector already holds this request lock')
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    deadline = time.monotonic() + seconds
    failures = 0
    base = dict(schema=1, request=request, host=socket.gethostname(), interval_s=interval)
    print(json.dumps(dict(event='started', **base)), flush=True)
    while not stop.is_set() and time.monotonic() < deadline and not (folder / 'stop').exists():
        start = time.monotonic()
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=' + FIELDS,
                                     '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, check=True, timeout=8)
            sample = dict(base, collected_at=time.time(), state='ok', gpus=parse_csv(result.stdout))
            failures = 0
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            failures += 1
            sample = dict(base, collected_at=time.time(), state='error', gpus=[],
                          error=type(error).__name__)
        atomic_json(folder / 'latest.json', sample)
        if failures >= 3:
            raise SystemExit('GPU sampling failed three times; collector stopped without restart')
        stop.wait(max(0, interval - (time.monotonic() - start)))
    atomic_json(folder / 'latest.json', dict(base, collected_at=time.time(),
                                           state='stopped', gpus=[]))
    print(json.dumps(dict(event='stopped', **base)), flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    run = sub.add_parser('collect')
    run.add_argument('--request', required=True, type=lambda x: str(uuid.UUID(x)))
    run.add_argument('--seconds', type=int, default=64800)
    run.add_argument('--interval', type=float, default=5)
    sub.add_parser('xml')
    sub.add_parser('status')
    args = parser.parse_args()
    if args.action == 'collect':
        if not 1 <= args.seconds <= 64800 or not 5 <= args.interval <= 60:
            parser.error('Duration must be 1–64800 seconds; interval must be 5–60 seconds')
        collect(args.request, args.seconds, args.interval)
        return
    data = latest()
    if args.action == 'xml':
        # A missing, failed, stopped or expired sample must never appear live.
        if fresh(data):
            print(as_xml(data))
        return
    print(status_text(data))


if __name__ == '__main__':
    main()
