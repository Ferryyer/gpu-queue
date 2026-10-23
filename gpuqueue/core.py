import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

HOME = Path.home().resolve()
DEFAULT_ROOT = HOME / '.local/state/gpuq'
SITE_URL = 'http://127.0.0.1:8790'
TERMINAL = {'completed', 'failed', 'interrupted', 'blocked', 'cancelled', 'stopped'}

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(canonical(value))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default

def private_path(value, *, directory=False):
    path = Path(value).expanduser().resolve()
    if not path.is_relative_to(HOME) or not path.exists():
        raise ValueError(f'路径必须存在并位于本人 HOME：{value}')
    if directory and not path.is_dir():
        raise ValueError(f'不是目录：{value}')
    return path

def fingerprint(path):
    path = Path(path)
    stat = path.stat()
    result = {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'directory': path.is_dir()}
    if path.is_file() and stat.st_size <= 8 * 1024 * 1024:
        result['sha256'] = sha(path)
    return result

def normalize(manifest, source='Codex'):
    if not isinstance(manifest, dict) or manifest.get('schema_version', 1) != 1:
        raise ValueError('需要 schema_version=1 的 JSON 任务文件')
    title = manifest.get('title', '').strip()
    if not title or len(title) > 160:
        raise ValueError('title 必填，最长 160 字符')
    if not isinstance(manifest.get('project'), str) or not Path(manifest['project']).is_absolute():
        raise ValueError('project 必须是本人 HOME 内的项目绝对路径')
    project = private_path(manifest['project'], directory=True)
    resources = dict(manifest.get('resources') or {})
    resources.setdefault('gpus', 1)
    resources.setdefault('type', 'H卡离线')
    resources.setdefault('estimated_hours', 17)
    resources.setdefault('memory_gb', None)
    if type(resources['gpus']) is not int or not 1 <= resources['gpus'] <= 4:
        raise ValueError('单个任务申请 1–4 张 GPU')
    if resources['type'] not in ['H卡离线', '4090联网']:
        raise ValueError('未知资源类型')
    if not isinstance(resources['estimated_hours'], (int, float)) or not 0 < resources['estimated_hours'] < 18:
        raise ValueError('预计时长是规划值，须大于 0 且短于 18 小时')
    memory = resources['memory_gb']
    if memory is not None and (not isinstance(memory, (int, float)) or memory <= 0):
        raise ValueError('memory_gb 为每卡显存需求的正数，未知时留空并保持串行')
    code_files = manifest.get('code_files')
    if not isinstance(code_files, list) or not code_files:
        raise ValueError('code_files 必须列出要固定版本的代码和配置文件或子目录')
    files = {}
    total = 0
    for item in code_files:
        item = Path(item)
        if item.is_absolute() or '..' in item.parts or str(item) in ['', '.']:
            raise ValueError('code_files 使用项目内的具体相对路径，不接受整个项目根目录')
        path = (project / item).resolve()
        if not path.is_relative_to(project) or not path.exists():
            raise ValueError(f'代码路径无效：{item}')
        candidates = [path] if path.is_file() else sorted(path.rglob('*'))
        for candidate in candidates:
            if candidate.is_dir():
                continue
            relative = candidate.relative_to(project)
            if any(p.startswith('.') or p in ['__pycache__', 'node_modules'] for p in relative.parts):
                continue
            if candidate.suffix in ['.pyc', '.pem', '.key'] or 'credentials' in candidate.name.lower():
                continue
            if not candidate.resolve().is_relative_to(project) or not candidate.is_file():
                raise ValueError('代码快照不允许跨项目软链接或特殊文件')
            total += candidate.stat().st_size
            if total > 200 * 1024 * 1024 or len(files) >= 10000:
                raise ValueError('代码快照上限 200 MiB / 10000 文件；数据与权重请放 inputs')
            files[str(relative)] = sha(candidate)
    if not files:
        raise ValueError('没有可固定的代码文件')
    inputs = [fingerprint(private_path(p)) for p in manifest.get('inputs', [])]
    steps = manifest.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 50:
        raise ValueError('steps 需要 1–50 个有序步骤')
    normalized_steps = []
    runtimes = {}
    for index, raw in enumerate(steps):
        argv = raw.get('argv')
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and '\x00' not in a for a in argv):
            raise ValueError(f'步骤 {index + 1} 的 argv 必须是参数数组')
        executable = Path(argv[0]).expanduser()
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f'步骤 {index + 1} 需要当前已存在的绝对可执行路径')
        for argument in argv[1:]:
            if argument.startswith('{code}/'):
                relative = argument[len('{code}/'):]
                if relative not in files and not any(name.startswith(relative.rstrip('/')+'/') for name in files):
                    raise ValueError(f'步骤 {index + 1} 引用了未加入快照的代码或配置：{relative}')
        runtimes[str(executable)] = fingerprint(executable)
        outputs = raw.get('outputs', [])
        if not isinstance(outputs, list) or not all(isinstance(p, str) and p.startswith('{outputs}/') and '..' not in Path(p).parts for p in outputs):
            raise ValueError('outputs 须使用 {outputs}/ 下的具体文件路径')
        env = raw.get('env', {})
        if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
            raise ValueError('步骤 env 必须是字符串映射')
        if any(any(word in k.upper() for word in ['TOKEN', 'PASSWORD', 'SECRET', 'API_KEY']) for k in env):
            raise ValueError('任务文件不保存凭据；使用本人私有环境配置')
        if any(k in env for k in ['CUDA_VISIBLE_DEVICES', 'GPUQ_OUTPUT_DIR', 'GPUQ_TASK_ID']):
            raise ValueError('GPU 设备与任务目录由执行器指定')
        for a in argv[1:]:
            if a.startswith(str(project) + '/') and Path(a).is_file() and str(Path(a).relative_to(project)) in files:
                raise ValueError('运行代码请引用 {code}/文件，避免执行 Agent 后续修改的源文件')
        normalized_steps.append({'name': raw.get('name') or f'步骤 {index + 1}', 'argv': argv, 'cwd': raw.get('cwd', '{code}'), 'outputs': outputs, 'env': env})
    document = {'schema_version': 1, 'title': title, 'description': manifest.get('description', ''), 'project': str(project), 'resources': resources, 'steps': normalized_steps, 'files': files, 'inputs': inputs, 'runtimes': list(runtimes.values()), 'submission_key': manifest.get('submission_key', ''), 'runner_sha256': sha(Path(__file__).with_name('runner.py'))}
    digest = hashlib.sha256(canonical(document).encode()).hexdigest()
    return document, digest

class Store:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        with self.connect() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY,digest TEXT NOT NULL,doc TEXT NOT NULL,public TEXT NOT NULL,internal TEXT NOT NULL)')
            connection.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')

    def connect(self):
        connection = sqlite3.connect(self.root / 'queue.sqlite3', timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA synchronous=FULL')
        return connection

    def tasks(self):
        with self.connect() as connection:
            return [self.decode(row) for row in connection.execute('SELECT * FROM tasks ORDER BY rowid')]

    def get(self, task_id):
        with self.connect() as connection:
            row = connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            return self.decode(row) if row else None

    @staticmethod
    def decode(row):
        return {'id': row['id'], 'digest': row['digest'], **{k: json.loads(row[k]) for k in ['doc', 'public', 'internal']}}

    def save(self, task):
        with self.connect() as connection:
            connection.execute('UPDATE tasks SET public=?, internal=? WHERE id=?', (canonical(task['public']), canonical(task['internal']), task['id']))

    def metadata(self, key, value=None):
        with self.connect() as connection:
            if value is not None:
                connection.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, canonical(value)))
            row = connection.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def submit(self, manifest, source='Codex'):
        doc, digest = normalize(manifest, source)
        task_id = 'GQ-' + digest[:16]
        if self.get(task_id):
            return self.get(task_id), False
        folder = self.root / 'tasks' / task_id
        folder.parent.mkdir(exist_ok=True, mode=0o700)
        staging = Path(tempfile.mkdtemp(dir=folder.parent, prefix='.prepare-'))
        try:
            for relative, expected in doc['files'].items():
                target = staging / 'code' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(doc['project']) / relative, target)
                if sha(target) != expected:
                    raise ValueError('复制期间源代码发生变化，请重新准备后提交')
                target.chmod(0o400)
            shutil.copy2(Path(__file__).with_name('runner.py'), staging / 'runner.py')
            (staging / 'runner.py').chmod(0o400)
            atomic_json(staging / 'manifest.json', {'digest': digest, 'doc': doc})
            (staging / 'outputs').mkdir(mode=0o700)
            (staging / 'run').mkdir(mode=0o700)
            try:
                staging.rename(folder)
            except FileExistsError:
                pass
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        public = {'id': task_id, 'name': doc['title'], 'description': doc['description'], 'project': Path(doc['project']).name, 'agent': source, 'state': 'ready', 'stage': 0, 'progress': None, 'elapsed': '尚未运行', 'version': digest[:12], 'memory': doc['resources']['memory_gb'], 'resources': doc['resources'], 'steps': [s['name'] for s in doc['steps']], 'step_records': [], 'events': ['代码和配置已固定版本', 'CPU 准备检查通过，等待你在网页点击开始'], 'created_at': now(), 'checks': ['代码快照已校验', '输入路径已检查', '执行入口已检查', 'GPU 兼容性将在运行时验证']}
        task = {'id': task_id, 'digest': digest, 'doc': doc, 'public': public, 'internal': {'approved_at': None, 'position': 0, 'request_uuid': None, 'job_uuid': None, 'dispatch': None}}
        with self.connect() as connection:
            connection.execute('INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?)', (task_id, digest, canonical(doc), canonical(public), canonical(task['internal'])))
        return self.get(task_id), True
