#!/usr/bin/env python3
"""Read-only, single-process ServerBox status command for the current UID."""
import collections
import datetime
import json
import os
from pathlib import Path
import pwd
import re
import time


def own_status(path, uid):
    if path.stat().st_uid != uid:
        return None
    fields = dict(line.split(':', 1) for line in (path / 'status').read_text().splitlines() if ':' in line)
    # RLIMIT_NPROC is counted by real UID, not effective UID.
    if int(fields['Uid'].split()[0]) != uid:
        return None
    return fields


def nproc_limit(path, uid):
    try:
        if own_status(path, uid) is None:
            return '不可读'
        match = re.search(r'^Max processes\s+(\S+)\s+(\S+)', (path / 'limits').read_text(), re.M)
        if match:
            return '/'.join('无限制' if v == 'unlimited' else v for v in match.groups())
    except (OSError, ValueError, KeyError):
        pass
    return '不可读'


def sample(proc, uid, deadline=None):
    rows = []
    skipped = 0
    timed_out = False
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        if deadline is not None and time.monotonic() > deadline:
            timed_out = True
            break
        try:
            fields = own_status(path, uid)
            if fields is None:
                continue
            name = ' '.join(''.join(c for c in fields['Name'] if c.isprintable()).split())[:40]
            threads = int(fields['Threads'])
            if threads < 1:
                raise ValueError('invalid thread count')
            rows.append((int(path.name), name, threads))
        except (OSError, ValueError, KeyError):
            # A process can exit between the directory listing and status read.
            skipped += 1
    return rows, skipped, timed_out


def render(proc, home, uid, username):
    rows, skipped, timed_out = sample(proc, uid, time.monotonic() + 3)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%m-%d %H:%M:%S')
    lines = [f'{sum(row[2] for row in rows)} 个线程',
             f'{len(rows)} 个进程 · {username} · 北京时间 {now}',
             f'当前可见账号 UID {uid} 的进程快照']
    groups = collections.defaultdict(list)
    for pid, name, threads in rows:
        groups[name].append((pid, threads))
    lines.append('主要程序（线程 / 进程）')
    for name, items in sorted(groups.items(), key=lambda item: (-sum(t for _, t in item[1]), item[0]))[:8]:
        pid, threads = max(items, key=lambda item: item[1])
        lines.append(f'{name}: {sum(t for _, t in items)} / {len(items)} · 最大 PID {pid} ({threads})')
    lines.append('线程限制（软/硬，按启动来源继承）')
    lines.append(f'本次采集：{nproc_limit(proc / "self", uid)}')
    try:
        state = json.loads((home / '.local/state/markflow-services/status.json').read_text())
        pid = int(state['supervisor_pid'])
        if pid > 0:
            lines.append(f'服务监管器 PID {pid}：{nproc_limit(proc / str(pid), uid)}')
    except (OSError, ValueError, KeyError, TypeError):
        lines.append('服务监管器：未取得 PID')
    lines.append('总数为当前 /proc 可见快照，非 CPU/带宽占用；限制并非所有会话统一配额。')
    if skipped or timed_out:
        lines.append(f'部分采样：跳过 {skipped} 项' + ('，已到 3 秒采样时限' if timed_out else '（退出或不可读）'))
    return '\n'.join(lines)


if __name__ == '__main__':
    uid = os.getuid()
    try:
        print(render(Path('/proc'), Path.home(), uid, pwd.getpwuid(uid).pw_name))
    except OSError as error:
        print(f'线程采集不可用：{error.strerror or type(error).__name__}')
        raise SystemExit(1)
