#!/usr/bin/env python3
"""Generate the app's Dart build from pubspec, or reject stale release sources."""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent


def build_data(app):
    version = re.search(r'^version: ([0-9.]+)\+([0-9]+)$',
                        (app / 'pubspec.yaml').read_text(), re.M)
    if not version:
        raise ValueError('Expected a numeric version and build in pubspec.yaml')
    build = int(version.group(2))
    if build <= 0:
        raise ValueError('App build must be positive')
    if version.group(1) != f'2.0.{build}':
        raise ValueError('Release tag, artifact and build must use the same 2.0 build')
    return ('// Generated from pubspec.yaml by scripts/sync_app_version.py.\n'
            '// ignore_for_file: prefer_single_quotes\n\n'
            'abstract class BuildData {\n'
            '  static const String name = "GPU Queue";\n'
            f'  static const int build = {build};\n'
            '}\n')


def sync(app, *, check=False):
    target = app / 'lib/data/res/build_data.dart'
    expected = build_data(app)
    if check:
        if not target.exists() or target.read_text() != expected:
            raise ValueError('Dart/native build mismatch: run python3 scripts/sync_app_version.py')
    else:
        target.write_text(expected, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    sync(ROOT / 'serverbox', check=args.check)


if __name__ == '__main__':
    main()
