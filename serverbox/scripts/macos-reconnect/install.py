#!/usr/bin/env python3
"""Install sleep/network recovery for the existing private ServerBox tunnel."""
from datetime import datetime, timezone
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile

TUNNEL = 'local.servercat.linlishuo-tunnel'
RECOVERY = 'local.serverbox.linlishuo-recovery'


def tunnel_agent(home, previous):
    gateway = ['/usr/bin/ssh', '-F', str(home/'.ssh/markflow-linlishuo/config'),
               '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20',
               '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=10',
               '-o', 'ServerAliveCountMax=2', '-T', 'markflow-gateway']
    return dict(previous, ProgramArguments=[
        '/usr/bin/ssh', '-F', str(home/'.ssh/config'), '-N',
        '-L', '127.0.0.1:22224:127.0.0.1:22223',
        '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ConnectTimeout=30', '-o', 'ConnectionAttempts=1',
        '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
        '-o', 'ProxyCommand='+shlex.join(gateway), 'markflow-cpu'],
        KeepAlive=True, RunAtLoad=True, ThrottleInterval=10)


def recovery_agent(home, binary):
    log = str(home/'.local/state/servercat/recovery.log')
    return dict(Label=RECOVERY, ProgramArguments=[str(binary)], KeepAlive=True,
                RunAtLoad=True, ThrottleInterval=15,
                StandardOutPath=log, StandardErrorPath=log)


def write_plist(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            plistlib.dump(value, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if sys.platform != 'darwin':
        raise SystemExit('This installer requires macOS')
    os.umask(0o077)
    home = Path.home()
    agents = home/'Library/LaunchAgents'
    tunnel = agents/(TUNNEL+'.plist')
    recovery = agents/(RECOVERY+'.plist')
    original = plistlib.loads(tunnel.read_bytes())
    if original.get('Label') != TUNNEL:
        raise SystemExit('Existing private tunnel configuration did not match')
    state = home/'.local/state/servercat'
    backup = state/'backups'/('reconnect-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(tunnel, backup/tunnel.name)
    if recovery.exists():
        shutil.copy2(recovery, backup/recovery.name)
    libexec = home/'.local/libexec'
    libexec.mkdir(parents=True, exist_ok=True, mode=0o700)
    binary = libexec/'serverbox-tunnel-recovery'
    if binary.exists():
        shutil.copy2(binary, backup/binary.name)
    build = backup/'build'
    build.mkdir(mode=0o700)
    candidate = build/binary.name
    subprocess.run(['swiftc', '-O', '-swift-version', '5',
                    str(Path(__file__).with_name('TunnelRecovery.swift')), '-o', str(candidate)], check=True)
    candidate.chmod(0o700)
    domain = f'gui/{os.getuid()}'

    def stop(path):
        return subprocess.run(['/bin/launchctl', 'bootout', domain, str(path)],
                              capture_output=True, text=True, timeout=15)

    def start(path):
        subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(path)], check=True, timeout=15)

    if recovery.exists():
        stop(recovery)
    stop(tunnel)
    try:
        os.replace(candidate, binary)
        write_plist(tunnel, tunnel_agent(home, original))
        write_plist(recovery, recovery_agent(home, binary))
        start(tunnel)
        start(recovery)
    except BaseException:
        stop(recovery)
        stop(tunnel)
        shutil.copy2(backup/tunnel.name, tunnel)
        if (backup/recovery.name).exists():
            shutil.copy2(backup/recovery.name, recovery)
            if (backup/binary.name).exists():
                shutil.copy2(backup/binary.name, binary)
            start(recovery)
        elif recovery.exists():
            recovery.rename(backup/'failed-recovery.plist')
        start(tunnel)
        raise
    print('Installed automatic tunnel recovery. Backup:', backup)


if __name__ == '__main__':
    main()
