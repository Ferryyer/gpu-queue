#!/usr/bin/env python3
"""Build the real flutter_pty native hook and test local shell I/O on CPU.

No app/Rust isolation substitutes for this hook: it is built from the vendored
package as a dependency. This is a PTY library test, not an SSH or Mac app test.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flutter', default='flutter')
    args = parser.parse_args()
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pty-native-', dir=build) as folder:
        harness = Path(folder)
        (harness / 'test').mkdir()
        (harness / 'pubspec.yaml').write_text(
            "name: gpuq_pty_native_checks\nenvironment:\n  sdk: '>=3.11.0 <4.0.0'\n"
            "dependencies:\n  flutter:\n    sdk: flutter\n  flutter_pty:\n"
            f"    path: {(ROOT / 'serverbox/packages/flutter_pty').as_posix()}\n"
            "dev_dependencies:\n  flutter_test:\n    sdk: flutter\n"
        )
        (harness / 'test/pty_native_test.dart').write_text(TEST)
        subprocess.run([args.flutter, 'test', '--timeout', '30s'], cwd=harness, check=True)


TEST = r'''
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_pty/flutter_pty.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('native PTY reports shell output, environment, directory and exit status', () async {
    final dir = await Directory.systemTemp.createTemp('gpuq-pty-');
    final pty = Pty.start('/bin/sh',
      arguments: ['-c', r'test -t 0 || exit 99; printf "%s:%s\n" "$PTY_FIXTURE" "$PWD"; exit 7'],
      workingDirectory: dir.path, environment: {'PTY_FIXTURE': 'cpu-native-fixture'});
    var exited = false;
    try {
      final output = pty.output.cast<List<int>>().transform(utf8.decoder).join();
      expect(await pty.exitCode.timeout(const Duration(seconds: 10)), 7);
      exited = true;
      final text = await output.timeout(const Duration(seconds: 10));
      expect(text, contains('cpu-native-fixture:${dir.path}'));
    } finally {
      if (!exited) pty.kill(ProcessSignal.sigkill);
      await dir.delete();
    }
  });
  test('native PTY input and resize reach the local shell', () async {
    final pty = Pty.start('/bin/sh', arguments: ['-c', r'IFS= read -r line; stty size; printf "received:%s\n" "$line"']);
    var exited = false;
    try {
      final output = pty.output.cast<List<int>>().transform(utf8.decoder).join();
      pty.resize(30, 100);
      pty.write(Uint8List.fromList(utf8.encode('fixture-input\n')));
      expect(await pty.exitCode.timeout(const Duration(seconds: 10)), 0);
      exited = true;
      final text = await output.timeout(const Duration(seconds: 10));
      expect(text, contains('30 100'));
      expect(text, contains('received:fixture-input'));
    } finally {
      if (!exited) pty.kill(ProcessSignal.sigkill);
    }
  });
  test('native PTY terminates only its owned shell and reports a signal', () async {
    final pty = Pty.start('/bin/sh', arguments: ['-c', 'exec sleep 30']);
    final output = pty.output.drain<void>();
    expect(pty.kill(ProcessSignal.sigkill), isTrue);
    expect(await pty.exitCode.timeout(const Duration(seconds: 10)), -9);
    await output.timeout(const Duration(seconds: 10));
  });
}
'''

if __name__ == '__main__':
    main()
