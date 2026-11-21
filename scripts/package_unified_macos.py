#!/usr/bin/env python3
"""Inspect a unified app and produce its DMG + SHA-256 manifest on macOS."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import tempfile
import shutil

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.search(r'^version: (.+)$', (ROOT/'serverbox/pubspec.yaml').read_text(), re.M).group(1)
MARKETING, BUILD = VERSION.split('+')

def inspect_app(app):
    app = Path(app).resolve()
    with (app/'Contents/Info.plist').open('rb') as handle:
        info = plistlib.load(handle)
    if str(info.get('CFBundleVersion')) != BUILD or info.get('CFBundleShortVersionString') != MARKETING:
        raise ValueError('Bundle version does not match serverbox/pubspec.yaml')
    executable = info.get('CFBundleExecutable', '')
    if not executable or '/' in executable or not (app/'Contents/MacOS'/executable).is_file():
        raise ValueError('Missing or invalid application executable')
    if not info.get('CFBundleIdentifier'):
        raise ValueError('Missing bundle identifier')
    return {'version': MARKETING, 'build': int(BUILD), 'bundleId': info['CFBundleIdentifier'], 'app': app.name}

def main():
    from sync_app_version import sync
    sync(ROOT / 'serverbox', check=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=ROOT/'build/unified-release')
    parser.add_argument('--inspect-only', action='store_true')
    parser.add_argument('--allow-unsigned', action='store_true', help='QA only: artifact is named unsigned and excluded from updater selection')
    args = parser.parse_args()
    metadata = inspect_app(args.app)
    if args.inspect_only:
        print(json.dumps(metadata, ensure_ascii=False)); return
    if platform.system() != 'Darwin':
        raise RuntimeError('DMG packaging requires macOS, Xcode signing tools and a real built .app')
    if not args.allow_unsigned:
        subprocess.run(['codesign','--verify','--deep','--strict',str(args.app)],check=True)
        subprocess.run(['spctl','--assess','--type','execute',str(args.app)],check=True)
    args.out.mkdir(parents=True, exist_ok=True)
    arch = platform.machine()
    if arch not in ['arm64', 'x86_64']:
        raise ValueError('Unsupported macOS architecture')
    name = f'Inspire-Queue-macos-{arch}-{BUILD}{"-unsigned" if args.allow_unsigned else ""}.dmg'
    target = args.out/name
    if target.exists():
        raise FileExistsError(target)
    with tempfile.TemporaryDirectory(prefix='gpuq-dmg-', dir=args.out) as folder:
        work = Path(folder)
        stage = work/'payload'
        stage.mkdir()
        subprocess.run(['ditto', str(args.app), str(stage/'Inspire Queue.app')],check=True)
        # Released 2007 installers look for this exact bundle path. ditto
        # dereferences a source-root link into a real app without copying the
        # link's hidden flag; Finder presents only the new product name.
        legacy = stage/'GPU Queue.app'
        legacy.symlink_to('Inspire Queue.app')
        subprocess.run(['chflags', '-h', 'hidden', str(legacy)],check=True)
        (stage/'Applications').symlink_to('/Applications')
        writable = work/'writable.dmg'
        mount = work/'volume'
        mount.mkdir()
        subprocess.run(['hdiutil','create','-volname','Inspire Queue','-srcfolder',str(stage),'-format','UDRW',str(writable)],check=True)
        subprocess.run(['hdiutil','attach','-nobrowse','-mountpoint',str(mount),str(writable)],check=True)
        try:
            # hdiutil -srcfolder drops symlink file flags. Set this on the
            # image filesystem before read-only compression instead.
            subprocess.run(['chflags','-h','hidden',str(mount/'GPU Queue.app')],check=True)
        finally:
            subprocess.run(['hdiutil','detach',str(mount)],check=True)
        subprocess.run(['hdiutil','convert',str(writable),'-format','UDZO','-o',str(target)],check=True)
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    legacy_name = name.replace('Inspire-Queue-', 'GPU-Queue-', 1)
    shutil.copy2(target, args.out/legacy_name)
    (args.out/'SHA256SUMS').write_text(f'{checksum}  {name}\n{checksum}  {legacy_name}\n')
    metadata.update(productName='Inspire Queue', artifact=name, legacyArtifact=legacy_name,
                    sha256=checksum, signedAndAssessed=not args.allow_unsigned, releaseTag=f'v{MARKETING}')
    (args.out/'unified-release.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(metadata,ensure_ascii=False))

if __name__ == '__main__':
    main()
