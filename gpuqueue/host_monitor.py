"""Expose the bundled ServerBox UID-only thread sampler without executing a shell."""
import importlib.util
import os
from pathlib import Path
import pwd
import time

HELPER = Path(__file__).resolve().parent.parent / 'serverbox/scripts/thread-monitor/status.py'


class HostMonitor:
    def __init__(self):
        self.module = None
        self.cached = None
        self.checked = float('-inf')

    def state(self):
        current = time.monotonic()
        if self.cached is not None and current - self.checked < 5:
            return self.cached
        try:
            if self.module is None:
                spec = importlib.util.spec_from_file_location('gpuq_serverbox_threads', HELPER)
                self.module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self.module)
            uid = os.getuid()
            text = self.module.render(Path('/proc'), Path.home(), uid, pwd.getpwuid(uid).pw_name)
            result = dict(available=True, at=time.time(), text=text)
        except (OSError, ValueError, KeyError, ImportError):
            # Keep an old successful result separate; a failed read is never a live zero.
            result = dict(available=False, at=None, text='账号线程采集暂不可用',
                          last_success=self.cached if self.cached and self.cached.get('available') else
                          (self.cached or {}).get('last_success'))
        self.cached, self.checked = result, time.monotonic()
        return result
