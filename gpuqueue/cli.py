import argparse
import json
import os
from pathlib import Path
import sys
from .core import Store, HOME, SITE_URL, normalize, read_json

def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog='gpuq', description='准备任务并提交到个人 GPU 任务台。只有网页上的“开始”可以授权执行。')
    subs = parser.add_subparsers(dest='action', required=True)
    for name in ['validate', 'submit']:
        sub = subs.add_parser(name)
        sub.add_argument('--manifest', required=True, help='JSON 任务文件')
        sub.add_argument('--source', default='Codex', choices=['Codex', 'Claude', 'codex', 'claude'])
    status = subs.add_parser('status')
    status.add_argument('task_id', nargs='?')
    subs.add_parser('doctor')
    subs.add_parser('web')
    serve = subs.add_parser('serve')
    serve.add_argument('--config', default=str(HOME/'.config/gpuq/connection.json'))
    args = parser.parse_args(argv)
    if args.action in ['validate', 'submit']:
        document = json.loads(Path(args.manifest).expanduser().read_text())
        if args.action == 'validate':
            normalized, digest = normalize(document, args.source)
            print(json.dumps({'ok': True, 'digest': digest, 'steps': [s['name'] for s in normalized['steps']], 'resources': normalized['resources'], 'note': '仅 CPU 检查通过，GPU 兼容性在运行时验证；尚未申请或使用 GPU'}, ensure_ascii=False))
        else:
            task, created = Store().submit(document, args.source.capitalize() if args.source.lower() == 'claude' else 'Codex')
            print(json.dumps({'ok': True, 'task_id': task['id'], 'created': created, 'state': task['public']['state'], 'url': SITE_URL+'/?task='+task['id'], 'note': '任务已提交；等待你在网页点击开始。未申请 GPU。'}, ensure_ascii=False))
    elif args.action == 'status':
        store = Store()
        tasks = [store.get(args.task_id)] if args.task_id else store.tasks()
        print(json.dumps([t['public'] for t in tasks if t], ensure_ascii=False, indent=2))
    elif args.action == 'web':
        from .web import serve as serve_web
        serve_web()
    elif args.action == 'doctor':
        store = Store()
        print(json.dumps({'site_url': SITE_URL, 'backend': 'local', 'access': 'SSH', 'connection_configured': (HOME/'.config/gpuq/connection.json').is_file(), 'service': read_json(store.root/'service-status.json'), 'task_count': len(store.tasks()), 'gpu_requests_performed': False}, ensure_ascii=False))
    else:
        from .service import Service
        config_path = Path(args.config)
        if config_path.stat().st_uid != os.getuid() or config_path.stat().st_mode & 0o077:
            raise ValueError('服务配置必须是本人私有文件，权限 0600')
        config = json.loads(config_path.read_text())
        if config['home'] != str(HOME) or config['username'] != __import__('pwd').getpwuid(os.getuid()).pw_name:
            raise ValueError('服务配置的本人身份不匹配')
        Service(config).serve()

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
