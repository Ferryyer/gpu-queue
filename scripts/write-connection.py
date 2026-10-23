"""Receive service access through hidden stdin; never print credentials."""
import json
import os
from pathlib import Path
import pwd
import sys
import termios

os.umask(0o077)
old = termios.tcgetattr(sys.stdin)
hidden = termios.tcgetattr(sys.stdin)
hidden[3] &= ~termios.ECHO
termios.tcsetattr(sys.stdin, termios.TCSANOW, hidden)
print('Ready for private connection JSON on stdin (input is hidden).', flush=True)
try:
    data = json.loads(sys.stdin.readline())
finally:
    termios.tcsetattr(sys.stdin, termios.TCSANOW, old)
data.update(home=str(Path.home()), username=pwd.getpwuid(os.getuid()).pw_name, mf_gpu='/usr/local/bin/mf-gpu', lark_cli=str(Path.home()/'.local/bin/lark-cli'))
folder = Path.home()/'.config/gpuq'
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
path = folder/'connection.json'
fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as out:
    json.dump(data, out)
os.chmod(path, 0o600)
print('Private service connection saved.', flush=True)
