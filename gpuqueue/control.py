"""Local queue authority. Browser approvals are separate from scheduler snapshots."""
from .core import Store, canonical, now, atomic_json, TERMINAL

LIVE = {'ready', 'queued', 'waiting_gpu', 'checking_resources'}
DELETABLE = {'completed', 'cancelled', 'stopped', 'failed', 'interrupted'}

class ControlError(RuntimeError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status

class QueueChanged(ControlError):
    pass

class Control:
    def __init__(self, store=None):
        self.store = store or Store()
        with self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS controls (id TEXT PRIMARY KEY REFERENCES tasks(id), approved_at TEXT, claimed_at TEXT, position INTEGER NOT NULL DEFAULT 0)')
            columns = {r[1] for r in db.execute('PRAGMA table_info(controls)')}
            for column in ['stop_at', 'stopped_at']:
                if column not in columns:
                    db.execute('ALTER TABLE controls ADD COLUMN '+column+' TEXT')
            db.execute('CREATE TABLE IF NOT EXISTS queue_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO queue_meta VALUES ('revision','0')")
            db.execute('CREATE TABLE IF NOT EXISTS queue_audit (id INTEGER PRIMARY KEY,task_id TEXT,action TEXT NOT NULL,at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS task_deletions (id TEXT PRIMARY KEY REFERENCES tasks(id),digest TEXT NOT NULL,deleted_at TEXT NOT NULL)')

    @staticmethod
    def revision(db):
        return int(db.execute("SELECT value FROM queue_meta WHERE key='revision'").fetchone()[0])

    def _state(self, db, *, include_deleted=False):
        visible = '' if include_deleted else ' WHERE NOT EXISTS (SELECT 1 FROM task_deletions WHERE task_deletions.id=tasks.id)'
        rows = db.execute('SELECT tasks.*, controls.approved_at,controls.claimed_at,controls.stop_at,controls.stopped_at,COALESCE(controls.position,0) AS position FROM tasks LEFT JOIN controls ON tasks.id=controls.id'+visible+' ORDER BY position,tasks.rowid').fetchall()
        tasks = []
        import json
        for row in rows:
            task = json.loads(row['public'])
            if row['approved_at'] and task['state'] == 'ready':
                task['state'] = 'queued'
            if row['claimed_at'] and task['state'] in LIVE:
                task['state'] = 'dispatching'
            if row['stop_at'] and task['state'] != 'completed':
                task['state'] = 'cancelled' if not row['claimed_at'] else 'stopped' if row['stopped_at'] else 'stopping'
            task.update(digest=row['digest'], approved_at=row['approved_at'], claimed_at=row['claimed_at'], position=row['position'], stop_requested_at=row['stop_at'], stopped_at=row['stopped_at'])
            tasks.append(task)
        heartbeat = db.execute("SELECT value FROM queue_meta WHERE key='heartbeat'").fetchone()
        return {'revision': self.revision(db), 'tasks': tasks, 'heartbeat': json.loads(heartbeat[0]) if heartbeat else None, 'capabilities': {'task_delete': True}}

    def _check_delete(self, db, task):
        import json
        row = db.execute('SELECT internal FROM tasks WHERE id=?', (task['id'],)).fetchone()
        internal = json.loads(row['internal'])
        if internal.get('dispatch') in {'submitting', 'unknown'}:
            raise ControlError('执行状态尚未确认，不能删除此任务')
        if task['state'] not in DELETABLE and not (
                task['state'] == 'ready' and not task['approved_at'] and not task['claimed_at']):
            raise ControlError('请先停止任务，等待服务器确认结束后再删除')

    def _delete_records(self, db, tasks):
        at = now()
        for task in tasks:
            db.execute('INSERT INTO task_deletions VALUES (?,?,?)', (task['id'], task['digest'], at))
            db.execute('INSERT INTO queue_audit(task_id,action,at) VALUES (?,?,?)',
                       (task['id'], 'delete_record:'+task['digest'], at))
        if tasks:
            db.execute("UPDATE queue_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
        return self._state(db)

    def delete(self, task_id, digest):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row:
                raise ControlError('任务不存在', 404)
            if row['digest'] != digest:
                raise ControlError('任务版本已变化，请刷新后重试')
            if db.execute('SELECT 1 FROM task_deletions WHERE id=?', (task_id,)).fetchone():
                return self._state(db)
            task = next(t for t in self._state(db)['tasks'] if t['id'] == task_id)
            self._check_delete(db, task)
            return self._delete_records(db, [task])

    def cleanup(self, ids, revision):
        # Explicit IDs bind deletion to the confirmation the user saw. Newly
        # completed tasks must not be swept into an already confirmed batch.
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 250 or
                any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or
                type(revision) is not int):
            raise ControlError('清理请求无效，请刷新后重试', 400)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._state(db)
            if state['revision'] != revision:
                raise QueueChanged('任务列表已更新，请刷新后重新确认')
            current = {t['id']: t for t in state['tasks']}
            tasks = []
            for task_id in ids:
                task = current.get(task_id)
                if not task or task['state'] not in {'completed', 'cancelled'}:
                    raise QueueChanged('待清理任务的状态已变化，请刷新后重新确认')
                self._check_delete(db, task)
                tasks.append(task)
            return self._delete_records(db, tasks)

    def state(self):
        with self.store.connect() as db:
            db.execute('BEGIN')
            return self._state(db)

    def start(self, task_id, digest):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._state(db)
            task = next((t for t in state['tasks'] if t['id'] == task_id), None)
            if not task:
                raise ControlError('任务不存在', 404)
            if task['digest'] != digest:
                raise ControlError('任务版本已变化，请刷新后查看')
            if task['stop_requested_at']:
                raise ControlError('这一版任务已请求停止；再次运行请提交新版本')
            if task['approved_at']:
                return state
            if task['state'] != 'ready':
                raise ControlError('只有准备完成的任务可以启动')
            position = max((t['position'] for t in state['tasks']), default=0) + 1
            at = now()
            db.execute('INSERT INTO controls(id,approved_at,position) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET approved_at=excluded.approved_at,position=excluded.position', (task_id, at, position))
            db.execute("UPDATE queue_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
            db.execute('INSERT INTO queue_audit(task_id,action,at) VALUES (?,?,?)', (task_id, 'browser_start:'+digest, at))
            return self._state(db)

    def reorder(self, ids, revision):
        if not isinstance(ids, list) or any(not isinstance(i,str) for i in ids) or len(set(ids)) != len(ids):
            raise ControlError('队列格式无效', 400)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._state(db)
            eligible = {t['id'] for t in current['tasks'] if t['approved_at'] and not t['claimed_at'] and t['state'] in LIVE}
            if current['revision'] != revision or set(ids) != eligible:
                raise QueueChanged('队列已更新，请刷新后重试')
            for position, task_id in enumerate(ids):
                db.execute('UPDATE controls SET position=? WHERE id=?', (position, task_id))
            db.execute("UPDATE queue_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
            db.execute('INSERT INTO queue_audit(action,at) VALUES (?,?)', ('browser_reorder:'+canonical(ids), now()))
            return self._state(db)

    def claim(self, task_id, digest, revision):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._state(db)
            task = next((t for t in state['tasks'] if t['id'] == task_id), None)
            if not task or task['digest'] != digest or not task['approved_at'] or task['stop_requested_at']:
                raise QueueChanged('尚未获得这一版任务的网页启动授权')
            if task['claimed_at']:
                return {'claimed': True, 'at': task['claimed_at']}
            if state['revision'] != revision:
                raise QueueChanged('队列刚刚变化，下一轮同步后继续')
            eligible = [t for t in state['tasks'] if t['approved_at'] and not t['claimed_at'] and t['state'] in LIVE]
            if not eligible or eligible[0]['id'] != task_id:
                raise QueueChanged('队列顺序已变化')
            at = now()
            db.execute('UPDATE controls SET claimed_at=? WHERE id=?', (at, task_id))
            db.execute("UPDATE queue_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
            return {'claimed': True, 'at': at}

    def sync(self, heartbeat):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT INTO queue_meta VALUES ('heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (canonical({**heartbeat, 'at': now()}),))
            # Keep stop authorizations visible to the scheduler even when a
            # cancelled row was deleted before its next synchronization.
            return self._state(db, include_deleted=True)

    def stop(self, task_id, digest):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._state(db)
            task = next((t for t in state['tasks'] if t['id'] == task_id), None)
            if not task:
                raise ControlError('任务不存在', 404)
            if task['digest'] != digest:
                raise ControlError('任务版本已变化，请刷新后重试')
            if task['state'] in TERMINAL:
                return state
            at = task['stop_requested_at'] or now()
            if not task['stop_requested_at']:
                db.execute('INSERT INTO controls(id,stop_at) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET stop_at=excluded.stop_at', (task_id, at))
                db.execute("UPDATE queue_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
                db.execute('INSERT INTO queue_audit(task_id,action,at) VALUES (?,?,?)', (task_id, 'browser_stop:'+digest, at))
        # Live control marker, separate from the immutable approved code.
        atomic_json(self.store.root/'tasks'/task_id/'run/stop.json', {'task':task_id,'digest':digest,'at':at})
        return self.state()

    def confirm_stop(self, task_id, digest):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT tasks.digest,controls.stop_at FROM tasks JOIN controls ON tasks.id=controls.id WHERE tasks.id=?', (task_id,)).fetchone()
            if not row or row['digest'] != digest or not row['stop_at']:
                raise ControlError('没有对应的网页停止请求')
            db.execute('UPDATE controls SET stopped_at=COALESCE(stopped_at,?) WHERE id=?', (now(),task_id))

    def import_snapshot(self, snapshot):
        """One-shot migration; never replace subsequent local browser decisions."""
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM queue_meta WHERE key='migration'").fetchone():
                raise ControlError('迁移记录已导入，拒绝覆盖本地启动授权')
            if db.execute('SELECT COUNT(*) FROM controls').fetchone()[0]:
                raise ControlError('本地已有启动记录，不能覆盖')
            for remote in snapshot['tasks']:
                local = db.execute('SELECT digest FROM tasks WHERE id=?', (remote['id'],)).fetchone()
                if not local or local['digest'] != remote['digest']:
                    raise ControlError('迁移任务版本不匹配：'+remote['id'])
                db.execute('INSERT INTO controls(id,approved_at,claimed_at,position) VALUES (?,?,?,?)', (remote['id'], remote.get('approved_at'), remote.get('claimed_at'), remote['position']))
            db.execute("UPDATE queue_meta SET value=? WHERE key='revision'", (str(snapshot['revision']),))
            db.execute("INSERT INTO queue_meta VALUES ('migration',?)", (canonical({'at':now(),'source':'retired-sites'}),))
            db.execute('INSERT INTO queue_audit(action,at) VALUES (?,?)', ('import_approved_snapshot', now()))
            return self._state(db)
