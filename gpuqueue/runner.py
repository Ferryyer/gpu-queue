"""Foreground GPU pipeline. Reads immutable input; never applies for resources."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import selectors

def write(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()

def expand(value, folder, doc):
    for key, replacement in {'code': folder/'code', 'outputs': folder/'outputs', 'home': Path.home(), 'project': doc['project']}.items():
        value = value.replace('{'+key+'}', str(replacement))
    return value

def execute(folder):
    folder = Path(folder).resolve()
    run = folder / 'run'
    state_file = run / 'status.json'
    claim = run / 'attempt.claim'
    # Atomic across GPU hosts and invocations. An interrupted attempt is never retried.
    fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    plan = json.loads((folder/'manifest.json').read_text())
    approval = json.loads((run/'approval.json').read_text())
    doc = plan['doc']
    status = {'state': 'starting', 'stage': 0, 'steps': [], 'started_at': time.time(), 'updated_at': time.time()}
    write(state_file, status)
    try:
        if approval.get('digest') != plan['digest'] or not approval.get('approved_at'):
            raise ValueError('Missing matching browser approval')
        canonical = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if hashlib.sha256(canonical.encode()).hexdigest() != plan['digest']:
            raise ValueError('Task manifest changed after submission')
        if sha(Path(__file__)) != doc['runner_sha256']:
            raise ValueError('Pipeline runner changed after submission')
        for relative, digest in doc['files'].items():
            if sha(folder/'code'/relative) != digest:
                raise ValueError('Code snapshot changed after approval')
        for item in doc['inputs'] + doc['runtimes']:
            path = Path(item['path'])
            stat = path.stat()
            if stat.st_size != item['size'] or stat.st_mtime_ns != item['mtime_ns'] or ('sha256' in item and sha(path) != item['sha256']):
                raise ValueError('Input or runtime changed: '+item['path'])
        gpu = subprocess.run(['nvidia-smi', '--query-gpu=uuid', '--format=csv,noheader'], capture_output=True, text=True, timeout=30)
        if gpu.returncode or not gpu.stdout.strip():
            raise RuntimeError('GPU verification failed; refusing CPU fallback')
        device_ids = approval.get('gpu_uuids', [])
        if len(device_ids) != doc['resources']['gpus'] or not set(device_ids).issubset(set(gpu.stdout.split())):
            raise RuntimeError('Assigned GPU identity is unavailable')
        status['gpu_verified'] = True
        for index, step in enumerate(doc['steps']):
            # Verify the frozen code again at step boundaries.
            for relative, digest in doc['files'].items():
                if sha(folder/'code'/relative) != digest:
                    raise RuntimeError('Code snapshot changed during pipeline')
            record = {'name': step['name'], 'state': 'running', 'started_at': time.time(), 'outputs': []}
            status.update(state='running', stage=index, updated_at=time.time())
            status['steps'].append(record)
            write(state_file, status)
            env = dict(os.environ)
            for key, value in step['env'].items():
                env[key] = expand(value, folder, doc)
            env.update(CUDA_VISIBLE_DEVICES=','.join(device_ids), GPUQ_OUTPUT_DIR=str(folder/'outputs'), GPUQ_TASK_ID=folder.name, PYTHONDONTWRITEBYTECODE='1')
            argv = [expand(a, folder, doc) for a in step['argv']]
            cwd = Path(expand(step['cwd'], folder, doc)).resolve()
            if not cwd.is_relative_to(Path.home().resolve()) or not cwd.is_dir():
                raise ValueError('Working directory escaped HOME')
            log = run / f'step-{index}.log'
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            record['pid'] = process.pid
            write(state_file, status)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                for key, _ in selector.select(timeout=10):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if log.exists() and log.stat().st_size+len(chunk)>10*1024*1024:
                        os.replace(log, log.with_suffix('.previous.log'))
                    with log.open('ab') as stream:
                        stream.write(chunk)
                status['updated_at'] = time.time()
                write(state_file, status)
            selector.close()
            process.stdout.close()
            code = process.wait()
            record.update(exit_code=code, finished_at=time.time())
            if code != 0:
                record['state'] = 'failed'
                raise RuntimeError(f'{step["name"]} exited with code {code}')
            for output in step['outputs']:
                path = Path(expand(output, folder, doc)).resolve()
                if not path.is_relative_to((folder/'outputs').resolve()) or not path.is_file():
                    raise RuntimeError('Expected output missing: '+output)
                record['outputs'].append({'path': str(path), 'name': path.name, 'size': path.stat().st_size})
            record['state'] = 'completed'
            status['updated_at'] = time.time()
            write(state_file, status)
        status.update(state='completed', stage=len(doc['steps']), finished_at=time.time(), updated_at=time.time())
        write(state_file, status)
        return 0
    except BaseException as error:
        if status['steps'] and status['steps'][-1]['state'] == 'running':
            status['steps'][-1]['state'] = 'failed'
        status.update(state='failed', error=str(error), finished_at=time.time(), updated_at=time.time())
        write(state_file, status)
        print(type(error).__name__+': '+str(error), file=sys.stderr)
        return 1

if __name__ == '__main__':
    os.umask(0o077)
    sys.exit(execute(sys.argv[1]))
