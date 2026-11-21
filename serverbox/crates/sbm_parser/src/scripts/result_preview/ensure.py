"""Ensure the current user's private result service, without opening TCP ports.

Executed by Queue after binding its local listener. The bundled command
supplies BACKEND_B64; running this file directly uses the adjacent fileshare.py.
"""
import base64
import fcntl
import http.client
import os
from pathlib import Path
import pwd
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import time


def private_dir(path):
    path = Path(path)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f'目录必须属于本人且权限为 700：{path}')
    return path


def checked_socket(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('成果服务连接文件不属于本人，或权限不正确')
    return True


def healthy(path):
    if not checked_socket(path):
        return False
    connection = http.client.HTTPConnection('127.0.0.1', 8780, timeout=2)
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(2)
    try:
        connection.sock.connect(str(path))
        connection.request('HEAD', '/')
        response = connection.getresponse()
        if response.status != 200 or not response.getheader('Server', '').startswith('fshare'):
            raise RuntimeError('连接文件已有其他服务，未进行替换')
        return True
    except (ConnectionRefusedError, FileNotFoundError):
        return False
    finally:
        connection.close()


def atomic_file(path, data, mode=0o600):
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError(f'不覆盖非本人普通文件：{path}')
    fd, temporary = tempfile.mkstemp(prefix='.preview-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            os.fchmod(output.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bootstrap(home=None, socket_dir=None, backend=None):
    home = Path(home or pwd.getpwuid(os.getuid()).pw_dir)
    # Do not expose a home directory as a web root. Only fshare's explicit
    # registration list is served, including its existing tokens and paths.
    local = home / '.local'
    local.mkdir(mode=0o700, exist_ok=True)
    share = local / 'share'
    share.mkdir(mode=0o700, exist_ok=True)
    for parent in (home, local, share):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise RuntimeError(f'安装目录不可由其他账号写入：{parent}')
    state = private_dir(share / 'inspire-queue')
    state = private_dir(state / 'results')
    lock_fd = os.open(state / 'setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    process = None
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('另一次成果服务初始化尚未结束，请重试')
                time.sleep(0.2)
        directory = private_dir(socket_dir or f'/tmp/fileshare-{os.getuid()}')
        endpoint = directory / 'web.sock'
        alias = home / '.inspire-preview.sock'
        if alias.is_symlink():
            if alias.lstat().st_uid != os.getuid() or os.readlink(alias) != str(endpoint):
                raise RuntimeError('已有其他成果连接配置，未进行覆盖')
        elif alias.exists():
            raise RuntimeError('成果连接位置已有文件，未进行覆盖')

        if not healthy(endpoint):
            if backend is None:
                backend = (base64.b64decode(BACKEND_B64) if 'BACKEND_B64' in globals()
                           else Path(__file__).with_name('fileshare.py').read_bytes())
            program = state / 'fileshare.py'
            atomic_file(program, backend)
            log_fd = os.open(state / 'service.log', os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(log_fd, 'ab') as log:
                process = subprocess.Popen([sys.executable, '-I', str(program), 'serve'],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                    start_new_session=True, env={**os.environ, 'HOME': str(home),
                        'FSHARE_SOCK_DIR': str(directory),
                        'FSHARE_STATE_DIR': str(home / '.local/state/fileshare')})
            for _ in range(50):
                if healthy(endpoint):
                    break
                if process.poll() is not None:
                    raise RuntimeError('成果服务启动失败，请查看 ~/.local/share/inspire-queue/results/service.log')
                time.sleep(0.2)
            else:
                process.terminate()
                process.wait(timeout=3)
                raise RuntimeError('成果服务启动超时')
            # Preserve any existing fshare command. New users get a command
            # with the same registration format and localhost links.
            binaries = local / 'bin'
            binaries.mkdir(mode=0o700, exist_ok=True)
            launcher = binaries / 'fshare'
            if not launcher.exists() and not launcher.is_symlink():
                atomic_file(launcher, ('#!/bin/sh\nexec ' + shlex.quote(sys.executable) +
                    ' -I ' + shlex.quote(str(program)) + ' "$@"\n').encode(), 0o700)
        if not alias.is_symlink():
            os.symlink(str(endpoint), alias)
        return process
    finally:
        os.close(lock_fd)


if __name__ == '__main__':
    try:
        service = bootstrap()
        print('成果服务已就绪：复用本人私有连接，保留已有成果链接。')
    except Exception as error:
        print(f'成果服务初始化失败：{error}', file=sys.stderr)
        sys.exit(1)
