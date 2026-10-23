"""GPU-side task supervision and verified cancellation; standard library only.

This control program is copied separately from immutable computation snapshots.
It runs as the member UID on the original allocation, never as an administrator.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

class StopError(RuntimeError):
    pass

def read(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default

def write(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.stop-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, ensure_ascii=False);out.flush();os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def identity(pid):
    try:
        folder = Path('/proc')/str(int(pid))
        if folder.stat().st_uid != os.getuid(): return None
        fields = (folder/'stat').read_text().rsplit(')',1)[1].split()
        if fields[0] in ['Z','X']: return None
        return {'pid':int(pid),'start':int(fields[19]),'ppid':int(fields[1])}
    except (OSError, ValueError, IndexError): return None

def table():
    return {int(p.name): value for p in Path('/proc').iterdir() if p.name.isdigit() and (value := identity(p.name))}

def matches(value):
    current = identity(value['pid'])
    return current and current['start'] == value['start']

def descendants(roots, processes=None):
    processes = processes if processes is not None else table()
    found = {v['pid']:v for v in roots.values() if matches(v)}
    while True:
        added = {pid:v for pid,v in processes.items() if v['ppid'] in found and pid not in found}
        if not added: return found
        found.update(added)

def marked(folder, processes=None):
    """Find orphaned task children via two inherited, task-specific markers."""
    expected = [b'GPUQ_TASK_ID='+folder.name.encode(), b'GPUQ_OUTPUT_DIR='+str(folder/'outputs').encode()]
    result = {}
    for pid, value in (processes if processes is not None else table()).items():
        if pid == os.getpid(): continue
        try:
            environ = (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0')
            if all(item in environ for item in expected): result[pid] = value
        except OSError: pass
    return result

def send(value, sig):
    # pidfds bind the signal to the verified process, preventing PID reuse races.
    if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):
        raise StopError('GPU 内核或 Python 不支持安全的进程停止')
    if not matches(value): return
    try:
        fd = os.pidfd_open(value['pid'],0)
        try:
            if matches(value): signal.pidfd_send_signal(fd,sig)
        finally: os.close(fd)
    except ProcessLookupError: pass

def terminate(folder, owned, grace=5):
    owned = dict(owned); frozen = {}
    try:
        # Freeze verified parents first, then discover/freeze children. Include
        # previously tracked detached sessions and uniquely marked orphans.
        for _ in range(16):
            processes = table()
            owned.update(descendants(owned,processes));owned.update(marked(folder,processes))
            fresh = {pid:v for pid,v in owned.items() if pid not in frozen and matches(v)}
            if not fresh: break
            for pid, value in fresh.items(): send(value,signal.SIGSTOP);frozen[pid] = value
        else: raise StopError('子进程持续变化，未能确认停止范围')
        for value in owned.values():
            send(value,signal.SIGTERM);send(value,signal.SIGCONT)
        deadline = time.monotonic()+grace
        while time.monotonic()<deadline:
            if not any(matches(v) for v in owned.values()): break
            time.sleep(.1)
        # Catch task-marked children left during orderly shutdown, without
        # signalling any unrelated process or an allocation-wide process group.
        owned.update(marked(folder))
        for value in owned.values():
            if matches(value): send(value,signal.SIGKILL);send(value,signal.SIGCONT)
        deadline = time.monotonic()+2
        while time.monotonic()<deadline and any(matches(v) for v in owned.values()): time.sleep(.05)
        survivors = [v for v in owned.values() if matches(v)]
        if survivors: raise StopError('仍有任务进程未退出，停止状态待核查')
        return list(owned.values())
    finally:
        # Never leave a process suspended if a verification or permission check
        # failed part way through cancellation.
        for value in frozen.values():
            if matches(value): send(value,signal.SIGCONT)

def context(folder):
    folder = Path(folder).resolve()
    if not folder.is_relative_to(Path.home().resolve()) or folder.stat().st_uid != os.getuid():
        raise StopError('任务目录身份不匹配')
    plan = read(folder/'manifest.json')
    return folder, plan

def requested(folder, plan):
    marker = read(folder/'run/stop.json',{})
    return marker if marker.get('digest')==plan['digest'] and marker.get('task')==folder.name and marker.get('at') else None

def result(folder, plan, marker, state, **extra):
    dispatch = read(folder/'run/dispatch.json',{})
    value = {'state':state,'task':folder.name,'digest':plan['digest'],'stop_at':marker['at'],
             'uid':os.getuid(),'host':socket.gethostname(),'at':time.time(),
             'request':dispatch.get('request'),'job':dispatch.get('job'),**extra}
    write(folder/'run/stop-result.json',value)
    return value

def supervise(folder):
    folder, plan = context(folder)
    marker = requested(folder,plan)
    if marker:
        result(folder,plan,marker,'stopped',mode='supervisor',processes=[]);return 0
    argv = ['/usr/bin/python3','-I',str(folder/'runner.py'),str(folder)]
    env = dict(os.environ,GPUQ_TASK_ID=folder.name,GPUQ_OUTPUT_DIR=str(folder/'outputs'))
    process = subprocess.Popen(argv,env=env,start_new_session=True)
    owned = {}
    root = identity(process.pid)
    if root: owned[process.pid] = root
    interrupted = [False]
    def stop_signal(*_): interrupted[0] = True
    signal.signal(signal.SIGTERM,stop_signal);signal.signal(signal.SIGINT,stop_signal)
    while True:
        owned.update(descendants(owned))
        marker = requested(folder,plan)
        if marker or interrupted[0]:
            processes = terminate(folder,owned)
            process.wait(timeout=5)
            if marker: result(folder,plan,marker,'stopped',mode='supervisor',processes=processes)
            return 0 if marker else 143
        code = process.poll()
        if code is not None:
            # Task commands are foreground-only; clean up any task-owned children.
            leftovers = {pid:v for pid,v in owned.items() if matches(v)}
            leftovers.update(marked(folder))
            if leftovers: terminate(folder,leftovers)
            return code
        time.sleep(.5)

def stop_legacy(folder, request_id, job_id, jobs_root=None):
    folder, plan = context(folder)
    marker = requested(folder,plan)
    if not marker: raise StopError('没有匹配的网页停止请求')
    request_id, job_id = str(uuid.UUID(request_id)),str(uuid.UUID(job_id))
    jobs = Path(jobs_root) if jobs_root else Path.home()/'.local/state/markflow-gpu'/request_id/'jobs'
    specification = read(jobs/(job_id+'.json'),{})
    allowed = [
        ['/usr/bin/python3','-I',str(folder/'runner.py'),str(folder)],
        ['/usr/bin/python3','-I',str(folder/'run/stop-control.py'),'supervise',str(folder)]
    ]
    if specification.get('argv') not in allowed: raise StopError('计算入口与该任务不匹配，拒绝发送信号')
    for _ in range(60):
        status = read(jobs/job_id/'status.json',{})
        if status.get('state') in ['running','finished','failed']: break
        time.sleep(.5)
    else: raise StopError('GPU 尚未领取原任务，停止请求等待核查')
    owned = marked(folder)
    pid = status.get('pid')
    if pid and (root := identity(pid)):
        actual = (Path('/proc')/str(pid)/'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        expected = [a.encode() for a in specification['argv']]
        # mf-gpu writes its running receipt immediately after starting this PID.
        boot = next(int(s.split()[1]) for s in Path('/proc/stat').read_text().splitlines() if s.startswith('btime '))
        started = boot + root['start']/os.sysconf('SC_CLK_TCK')
        if actual != expected or abs(started-float(status.get('at',0)))>30:
            raise StopError('原任务进程身份或启动时间不匹配，拒绝发送信号')
        owned[pid] = root;owned.update(descendants(owned))
    elif status.get('state') == 'running' and not owned:
        raise StopError('原任务进程已失联，无法确认停止')
    processes = terminate(folder,owned)
    return result(folder,plan,marker,'stopped',mode='legacy',request=request_id,job=job_id,processes=processes)

def main():
    os.umask(0o077)
    mode, folder = sys.argv[1],sys.argv[2]
    if mode == 'supervise': return supervise(folder)
    folder, plan = context(folder)
    marker = requested(folder,plan)
    if not marker: raise StopError('没有匹配的网页停止请求')
    lock = (folder/'run/stop-control.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX)
    def confirmed():
        proof = read(folder/'run/stop-result.json',{})
        return proof.get('state')=='stopped' and proof.get('digest')==plan['digest'] and proof.get('stop_at')==marker['at']
    if confirmed(): return 0
    try:
        stop_legacy(folder,sys.argv[3],sys.argv[4]);return 0
    except Exception as error:
        if confirmed(): return 0
        result(folder,plan,marker,'unverified',mode='legacy',request=sys.argv[3],job=sys.argv[4],error=str(error))
        return 1

if __name__=='__main__':
    sys.exit(main())
