"""Isolated browser QA, using the production HTTP handler and local control DB."""
from http.server import HTTPServer
from pathlib import Path
import tempfile
from gpuqueue.core import HOME,Store,canonical,now
from gpuqueue.control import Control
from gpuqueue.web import Handler

temp = tempfile.TemporaryDirectory(dir=HOME/'scratch')
store = Store(Path(temp.name)/'state')
control = Control(store)
def task_id(n): return 'GQ-'+str(n).zfill(16)
def digest(n): return str(n).zfill(64)
for n in range(1,5):
    task={'id':task_id(n),'name':'真实链路测试 '+str(n),'description':'准备好后由用户启动','project':'test-project','agent':'Codex' if n%2 else 'Claude','state':'running' if n==1 else 'ready','stage':0,'progress':None,'elapsed':'尚未运行','version':digest(n)[:12],'memory':2,'resources':{'gpus':1,'memory_gb':2},'steps':['训练','评测','推理'],'step_records':[],'events':['CPU 检查通过'],'checks':['代码快照已校验','输入路径已检查','执行入口已检查','GPU 兼容性将在运行时验证'],'created_at':now()}
    if n==1: task['step_records']=[{'name':'训练','state':'running','log':'GPU test log: training step is running','outputs':[]}]
    with store.connect() as db: db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)',(task['id'],digest(n),'{}',canonical(task),'{}'))
with store.connect() as db:
    db.execute('INSERT INTO controls(id,approved_at,claimed_at,position) VALUES (?,?,?,?)',(task_id(1),now(),now(),0))
for n in [2,3]: control.start(task_id(n),digest(n))
control.sync({'resources':[],'service':'online'})
class TestHandler(Handler):
    def do_POST(self):
        if self.path=='/test/stop-confirm':
            task=store.get(task_id(1));task['public']['state']='stopped';store.save(task);control.confirm_stop(task['id'],task['digest'])
            return self.reply({'ok':True})
        if self.path=='/test/fail':
            task=store.get(task_id(1));task['public'].update(state='failed',stage=1,failureReason='测试：第二步失败',step_records=[{'name':'训练','state':'completed','log':'training complete','outputs':[]},{'name':'评测','state':'failed','log':'evaluation failed','outputs':[]}]);store.save(task)
            return self.reply({'ok':True})
        return super().do_POST()
server=HTTPServer(('127.0.0.1',8765),TestHandler)
server.control=control
server.assets=Path(__file__).resolve().parent.parent/'web'
print('Local Python QA server ready',flush=True)
try: server.serve_forever()
finally: server.server_close();temp.cleanup()
