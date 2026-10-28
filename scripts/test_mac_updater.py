#!/usr/bin/env python3
"""Exercise the real Swift installer against disposable signed fixture apps on macOS."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = r'''
import Cocoa
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let info = Bundle.main.infoDictionary!
let receipt = URL(fileURLWithPath: info["FixtureReceipt"] as! String)
let build = info["CFBundleVersion"] as! String
let value: [String: Any] = ["pid": ProcessInfo.processInfo.processIdentifier, "build": build]
try! JSONSerialization.data(withJSONObject: value).write(to: receipt, options: .atomic)
DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
  if info["FixtureAck"] as? Bool == true {
    let status = URL(fileURLWithPath: info["FixtureStatus"] as! String)
    if let data = try? Data(contentsOf: status),
       var state = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
       state["phase"] as? String == "awaiting_launch", state["build"] as? String == build {
      state["phase"] = "complete"
      try! JSONSerialization.data(withJSONObject: state).write(to: status, options: .atomic)
    }
  }
}
app.run()
'''


def run(*command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        print(result.stdout.decode(errors='replace'), file=sys.stderr)
        result.check_returncode()


def wait_for(predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Fixture deadline exceeded')


def read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    if sys.platform != 'darwin':
        raise RuntimeError('Native installer acceptance requires macOS; no simulated pass')
    out = ROOT / 'build/mac-updater-tests'
    out.mkdir(parents=True, exist_ok=True)
    helper = out / 'GPUQueueUpdater'
    run('swiftc', '-swift-version', '5', str(ROOT/'serverbox/macos/Updater/main.swift'), '-o', str(helper))
    results = []
    with tempfile.TemporaryDirectory(prefix='gpuq-installer-') as folder:
        root = Path(folder)
        source = root/'Fixture.swift'
        source.write_text(FIXTURE)
        fixture = root/'Fixture'
        run('swiftc', '-swift-version', '5', str(source), '-o', str(fixture))

        for scenario in ('success', 'legacy_payload', 'checksum_mismatch', 'wrong_bundle', 'quit_timeout', 'rollback', 'cancelled'):
            case = root/scenario
            case.mkdir()
            work = case/'work'
            work.mkdir()
            status = case/'state/status.json'
            receipt = case/'receipt.json'
            destination = case/'Inspire Queue.app'
            bundle_id = 'work.gpuqueue.updater.fixture.' + uuid.uuid4().hex
            pids = set()
            child = None
            log = (out/f'{scenario}.log').open('wb')
            try:
                def make_app(path, build, ack, identifier=bundle_id):
                    contents = path/'Contents'
                    (contents/'MacOS').mkdir(parents=True)
                    (contents/'MacOS/Fixture').write_bytes(fixture.read_bytes())
                    (contents/'MacOS/Fixture').chmod(0o755)
                    (contents/'Info.plist').write_bytes(plistlib.dumps({
                        'CFBundleExecutable': 'Fixture', 'CFBundleIdentifier': identifier,
                        'CFBundleVersion': str(build), 'CFBundleShortVersionString': f'2.0.{build}',
                        'CFBundleName': 'Inspire Queue Fixture', 'CFBundlePackageType': 'APPL',
                        'LSUIElement': True, 'FixtureAck': ack, 'FixtureStatus': str(status),
                        'FixtureReceipt': str(receipt),
                    }))
                    run('codesign', '--force', '--sign', '-', str(path))

                make_app(destination, 100, False)
                payload = case/'payload'
                payload_name = 'GPU Queue.app' if scenario == 'legacy_payload' else 'Inspire Queue.app'
                make_app(payload/payload_name, 101, scenario != 'rollback',
                         bundle_id if scenario != 'wrong_bundle' else 'work.gpuqueue.wrong')
                dmg = work/'update.dmg'
                run('hdiutil', 'create', '-srcfolder', str(payload), '-format', 'UDZO', str(dmg))
                run('open', '-n', str(destination))
                old = wait_for(lambda: read(receipt))
                pids.add(old['pid'])
                # User data is deliberately outside both application bundles.
                data = case/'settings.json'
                data.write_text('{"ssh":"keep","token":"fixture"}')
                plan = {'id': str(uuid.uuid4()), 'destination': str(destination), 'dmg': str(dmg),
                        'sha256': hashlib.sha256(dmg.read_bytes()).hexdigest(), 'build': '101',
                        'bundleID': bundle_id, 'pid': old['pid'], 'status': str(status),
                        'quitTimeout': 1.5 if scenario == 'quit_timeout' else 15., 'launchTimeout': 3.}
                if scenario == 'checksum_mismatch':
                    plan['sha256'] = '0' * 64
                if scenario == 'cancelled':
                    (work/'cancel').touch()
                planfile = work/'plan.json'
                planfile.write_text(json.dumps(plan))
                child = subprocess.Popen([str(helper), str(planfile)], stdout=log, stderr=log)
                if scenario in ('success', 'legacy_payload', 'rollback', 'quit_timeout'):
                    wait_for(lambda: read(status).get('phase') in ('ready', 'failed'))
                    assert read(status)['phase'] == 'ready', read(status)
                if scenario in ('success', 'legacy_payload', 'rollback'):
                    os.kill(old['pid'], signal.SIGTERM)
                code = child.wait(timeout=55)
                state = read(status)
                installed = plistlib.loads((destination/'Contents/Info.plist').read_bytes())
                if scenario in ('success', 'legacy_payload'):
                    assert code == 0 and state['phase'] == 'complete', state
                    assert installed['CFBundleVersion'] == '101'
                    assert Path(state['backup']).is_dir()
                    assert read(receipt)['build'] == '101'
                elif scenario == 'rollback':
                    assert code == 0 and state['phase'] == 'rolled_back', state
                    assert installed['CFBundleVersion'] == '100'
                    wait_for(lambda: read(receipt).get('build') == '100' and read(receipt).get('pid') != old['pid'])
                else:
                    assert code != 0 and state['phase'] == 'failed', state
                    assert installed['CFBundleVersion'] == '100'
                    os.kill(old['pid'], 0)  # A failed preflight never terminates the old application.
                assert data.read_text() == '{"ssh":"keep","token":"fixture"}'
                results.append({'scenario': scenario, 'passed': True})
                print(f'PASS {scenario}', flush=True)
            except Exception:
                log.flush()
                print((out/f'{scenario}.log').read_text(errors='replace'), file=sys.stderr)
                raise
            finally:
                if child and child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
                if read(receipt).get('pid'):
                    pids.add(read(receipt)['pid'])
                for pid in pids:
                    try:
                        # Only a fixture PID whose executable remains inside this test directory.
                        command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'comm='], text=True).strip()
                        if str(case) in command:
                            os.kill(pid, signal.SIGTERM)
                    except (ProcessLookupError, subprocess.CalledProcessError):
                        pass
                if (work/'volume').is_mount():
                    run('hdiutil', 'detach', '-force', str(work/'volume'))
                log.close()
    (out/'report.json').write_text(json.dumps({'native': True, 'scenarios': results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
