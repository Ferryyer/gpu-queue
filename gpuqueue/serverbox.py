"""Publish the personal queue's GPU lifecycle to the existing ServerBox probe."""
import math
from pathlib import Path
import time
import uuid
from .core import atomic_json
from .telemetry import monitor_status


def metric(value):
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError('Invalid GPU metric')
    return int(number) if number.is_integer() else number


def publish(resources, home):
    records = []
    for resource in resources.values():
        request = str(uuid.UUID(resource['id']))
        telemetry = resource.get('telemetry') or {}
        stamp = metric(telemetry.get('at')) or 0
        gpus = []
        for gpu in telemetry.get('gpus', []):
            gpus.append(dict(index=int(gpu['index']), uuid=gpu['uuid'], name=gpu['name'],
                             utilization_gpu_pct=metric(gpu['utilization']),
                             memory_used_mib=metric(gpu['used_mb']),
                             memory_total_mib=metric(gpu['total_mb']),
                             temperature_c=metric(gpu.get('temperature_c'))))
        records.append(dict(request=request, status=resource['status'],
                            collected_at=stamp, host=telemetry.get('host', ''), gpus=gpus,
                            monitor=monitor_status(resource), error=resource.get('error'), retry_at=resource.get('probe_retry_at'),
                            release_pending=resource.get('release', {}).get('state') == 'pending_interface'))
    path = Path(home)/'.local/state/serverbox-gpu/registry.json'
    atomic_json(path, dict(schema=1, source='gpuq', updated_at=time.time(), resources=records))
