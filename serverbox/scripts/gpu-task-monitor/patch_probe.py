#!/usr/bin/env python3
"""Apply the source probe change to this user's generated ServerBox script.

ServerBox regenerates its remote script on reconnect. Calling this idempotent
adapter as a custom status command preserves the opt-in integration without
changing the signed application or impersonating a system nvidia-smi binary.
"""
import os
from pathlib import Path
import stat
import tempfile

OLD = 'if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi -q -x; elif [ -x /usr/lib/wsl/lib/nvidia-smi ]; then /usr/lib/wsl/lib/nvidia-smi -q -x; fi'
NEW = OLD[:-2] + 'elif [ -x "$HOME/.local/bin/serverbox-gpu-status" ]; then "$HOME/.local/bin/serverbox-gpu-status" xml; fi'


def patch_script(path):
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        return False
    raw = path.read_text()
    if OLD not in raw:
        return False
    backup = path.with_suffix(path.suffix + '.before-gpu-monitor')
    try:
        with backup.open('x') as stream:
            stream.write(raw)
        backup.chmod(0o600)
    except FileExistsError:
        pass
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        stream.write(raw.replace(OLD, NEW))
        temp = Path(stream.name)
    temp.chmod(stat.S_IMODE(path.stat().st_mode))
    os.replace(temp, path)
    return True


def main():
    os.umask(0o077)
    for folder in [Path.home() / '.config/server_box', Path('/tmp/server_box')]:
        if folder.is_symlink():
            continue
        for path in folder.glob('srvboxm_v*.sh'):
            try:
                patch_script(path)
            except OSError:
                # An inaccessible script belongs to another connection/user.
                continue


if __name__ == '__main__':
    main()
