#!/usr/bin/env python3
"""Publish one reviewed daily note to the public calendar/notes path on main."""
import argparse
import base64
import datetime
import json
from pathlib import Path
import re
import subprocess
import tempfile

REPO = 'Ferryyer/gpu-queue'
MAX_BYTES = 64 * 1024


def validate(text, day):
    if datetime.date.fromisoformat(day).isoformat() != day:
        raise ValueError('Use YYYY-MM-DD')
    marker = f'<!-- inspire-calendar-date: {day} -->\n'
    if len(text.encode()) > MAX_BYTES or not text.startswith(marker):
        raise ValueError('Missing matching date marker or note exceeds 64 KiB')
    body = text[len(marker):].strip()
    if not body or '<' in body or '![' in body:
        raise ValueError('Use plain Markdown without HTML or embedded images')
    if re.search(r'PRIVATE KEY|gh[pousr]_[A-Za-z0-9]|github_pat_|/Users/|/home/|Bearer\s', body):
        raise ValueError('Remove credentials, local paths or private operational data')
    if 'https://' not in body or '置信度' not in body:
        raise ValueError('Include public source links and confidence before publishing')
    return text


def publish(text, day):
    endpoint = f'repos/{REPO}/contents/calendar/notes/{day}.md'
    probe = subprocess.run(['gh', 'api', endpoint+'?ref=main'], capture_output=True, text=True)
    payload = {'message': f'calendar: publish source notes for {day}', 'branch': 'main',
               'content': base64.b64encode(text.encode()).decode()}
    if probe.returncode == 0:
        existing = json.loads(probe.stdout)
        if base64.b64decode(existing['content']).decode() == text:
            return existing['html_url']
        payload['sha'] = existing['sha']
    elif 'HTTP 404' not in probe.stderr:
        raise RuntimeError('Cannot verify the existing GitHub note; nothing was written')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as request:
        json.dump(payload, request, ensure_ascii=False)
        request.flush()
        result = json.loads(subprocess.check_output(
            ['gh', 'api', endpoint, '--method', 'PUT', '--input', request.name], text=True))
    # Verify bytes from the immutable blob, not an eventually cached raw URL.
    content = result['content']
    blob = json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPO}/git/blobs/'+content['sha']], text=True))
    if base64.b64decode(blob['content']).decode() != text:
        raise RuntimeError('GitHub content verification failed')
    return content['html_url']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Validate without uploading')
    args = parser.parse_args()
    if args.file.stat().st_size > MAX_BYTES:
        parser.error('Note exceeds 64 KiB')
    text = validate(args.file.read_text(encoding='utf-8'), args.date)
    print('Note validated; nothing uploaded.' if args.check else publish(text, args.date))


if __name__ == '__main__':
    main()
