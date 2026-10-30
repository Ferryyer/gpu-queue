#!/usr/bin/env python3
"""Bundle the audited standalone result bootstrap; no download at runtime."""
import argparse
import base64
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'serverbox/crates/sbm_parser/src/scripts/result_preview'
TARGET = ROOT / 'serverbox/assets/result_preview.b64'
RELAY_TARGET = ROOT / 'serverbox/assets/result_preview_relay.b64'


def command():
    backend = base64.b64encode((SOURCE / 'fileshare.py').read_bytes()).decode()
    source = (SOURCE / 'ensure.py').read_text()
    return "python3 -I - <<'INSPIRE_PREVIEW_PY'\nBACKEND_B64 = " + repr(backend) + '\n' + source + '\nINSPIRE_PREVIEW_PY\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    relay = 'python3 -I -c ' + shlex.quote((SOURCE / 'relay.py').read_text())
    for target, text in ((TARGET, command()), (RELAY_TARGET, relay)):
        expected = base64.b64encode(text.encode()) + b'\n'
        if args.check:
            if target.read_bytes() != expected:
                raise SystemExit('Run scripts/build_result_preview_asset.py to synchronize the bundled script')
        else:
            target.write_bytes(expected)
