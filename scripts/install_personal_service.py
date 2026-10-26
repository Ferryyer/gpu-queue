#!/usr/bin/env python3
"""Inspect or install a disabled GPU Queue service for the current Linux user."""
import argparse
import json
import os
from pathlib import Path
import platform
import pwd
import shlex
import shutil
import stat
import sys


def identity():
    if platform.system() != 'Linux':
        raise ValueError('请在本人 Linux CPU 服务器运行；此工具不安装 Mac 客户端')
    if sys.version_info < (3, 10):
        raise ValueError('需要 Python 3.10 或更新版本')
    uid = os.getuid()
    if uid == 0 or uid != os.geteuid():
        raise ValueError('请以本人普通账号运行，不使用 sudo 或切换身份')
    account = pwd.getpwuid(uid)
    home = Path(account.pw_dir)
    if home.is_symlink() or Path.home().resolve() != home.resolve() or home.stat().st_uid != uid:
        raise ValueError('HOME 与当前 Linux 账号不匹配')
    if home.stat().st_mode & 0o077 or not 20000 <= uid < 30000:
        raise ValueError('mf-services 需要管理员已开通的普通成员账号和 0700 私有 HOME')
    return home.resolve(), account.pw_name, uid


def tool_path(name, home):
    candidates = [shutil.which(name), str(home/'.local/bin'/name), '/usr/local/bin/'+name]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).absolute())
    raise ValueError(f'未找到 {name}；请按团队工具指南配置本人 PATH 或联系管理员')


def check_path(path, home, uid):
    """Reject redirected or other-user paths without changing their permissions."""
    if not path.is_relative_to(home) or path == home:
        raise ValueError(f'安装路径必须位于本人 HOME：{path}')
    for part in [*reversed(path.parents), path]:
        if part == home or not part.is_relative_to(home):
            continue
        if part.is_symlink():
            raise ValueError(f'拒绝使用符号链接安装路径：{part}')
        if part.exists():
            info = part.stat()
            if info.st_uid != uid or info.st_mode & 0o022:
                raise ValueError(f'路径必须属于本人且不可被其他账号修改：{part}')
            if part != path and not part.is_dir():
                raise ValueError(f'父路径不是目录：{part}')


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def plan_install(source, home, username, uid):
    source = Path(source).resolve()
    if not source.is_relative_to(home):
        raise ValueError('请将发布源码放在本人 HOME 内，不从共享目录或其他账号目录安装')
    if not all((source/name).is_file() for name in ['gpuqueue/cli.py', 'gpuqueue/web.py', 'web/index.html']):
        raise ValueError('源码不完整：需要 gpuqueue/ 与 web/ 目录')
    tools = {name: tool_path(name, home) for name in ['mf-gpu', 'lark-cli', 'mf-services']}
    python = str(Path(sys.executable).absolute())
    config = {'backend': 'local', 'username': username, 'home': str(home),
              'mf_gpu': tools['mf-gpu'], 'lark_cli': tools['lark-cli']}
    launcher = ('#!/bin/sh\nset -eu\numask 077\n'
                'export HOME=' + shlex.quote(str(home)) + '\n'
                'cd ' + shlex.quote(str(source)) + '\n'
                'exec ' + shlex.quote(python) + ' -m gpuqueue.cli "$@"\n')
    bin_path = home/'.local/bin/gpuq'
    config_path = home/'.config/gpuq/connection.json'
    files = [(config_path, json_text(config), 0o600), (bin_path, launcher, 0o700)]
    for name, arguments in [('gpuq', ['serve', '--config', str(config_path)]), ('gpuq-web', ['web'])]:
        service = {'enabled': False, 'argv': [str(bin_path), *arguments],
                   'cwd': str(source), 'env': {}, 'restart': 'on-failure'}
        files.append((home/'.config/markflow/services'/f'{name}.json', json_text(service), 0o600))
    # Preflight every output before the first write. Existing configuration is
    # never overwritten, disabled, chmod'ed, or interpreted as fresh setup.
    changes = []
    for path, content, mode in files:
        check_path(path, home, uid)
        if path.exists():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != mode:
                raise ValueError(f'已有文件类型或权限不同，保留原文件：{path}')
            if path.suffix == '.json':
                same = json.loads(path.read_text()) == json.loads(content)
            else:
                same = path.read_text() == content
            if not same:
                raise ValueError(f'已有不同配置，保留原文件；请维护者核对迁移：{path}')
        else:
            changes.append((path, content, mode))
    return files, changes, tools


def apply_install(changes, home, uid):
    for path, content, mode in changes:
        check_path(path, home, uid)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # O_EXCL also rejects a path created since preflight; do not replace it.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='写入本人配置与禁用状态的服务登记；不启动服务')
    args = parser.parse_args(argv)
    home, username, uid = identity()
    source = Path(__file__).resolve().parent.parent
    files, changes, tools = plan_install(source, home, username, uid)
    if args.apply:
        os.umask(0o077)
        apply_install(changes, home, uid)
    print(json.dumps({'ok': True, 'mode': 'apply' if args.apply else 'dry-run',
                      'owner': username, 'uid': uid, 'home': str(home),
                      'python': sys.version.split()[0], 'tools': tools,
                      'files': [str(path) for path, _, _ in files],
                      'new_files': [str(path) for path, _, _ in changes],
                      'services_enabled': False, 'gpu_requests_performed': False,
                      'note': '未启动服务、未登录或发送消息。下一步运行 mf-services validate 并阅读 docs/EMPLOYEE-SETUP.md。'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(json.dumps({'ok': False, 'error': str(error), 'gpu_requests_performed': False}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
