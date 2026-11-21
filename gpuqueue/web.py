"""Private HTTP over a Unix socket. Access is through the owner's SSH session."""
import fcntl
from http.server import BaseHTTPRequestHandler
import json
import os
import pwd
from pathlib import Path
import re
import socketserver
import stat
from .core import Store, canonical
from .control import Control, ControlError
from .host_monitor import HostMonitor

ASSETS = {'/detail-modal.js': ('detail-modal.js','text/javascript; charset=utf-8'), '/monitor.js': ('monitor.js','text/javascript; charset=utf-8'), '/': ('index.html','text/html; charset=utf-8'), '/index.html': ('index.html','text/html; charset=utf-8'), '/style.css': ('style.css','text/css; charset=utf-8'), '/app.js': ('app.js','text/javascript; charset=utf-8'), '/model.js': ('model.js','text/javascript; charset=utf-8')}
SOCKET = Path('/tmp') / f'gpuq-{os.getuid()}' / 'web.sock'

class Handler(BaseHTTPRequestHandler):
    server_version = 'InspireQueue'
    sys_version = ''
    def log_message(self, *args):
        pass
    def reply(self, data, status=200, content_type='application/json; charset=utf-8'):
        body = data if isinstance(data, bytes) else canonical(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        self.handle_request()
    def do_POST(self):
        self.handle_request()
    def handle_request(self):
        self.connection.settimeout(10)
        host = self.headers.get('Host', '')
        if not re.fullmatch(r'(?:127\.0\.0\.1|localhost):[0-9]{1,5}', host):
            return self.reply({'error':'请通过本人 SSH 转发访问本地地址'}, 403)
        path = self.path.split('?',1)[0]
        try:
            if self.command == 'GET':
                if path == '/api/health':
                    return self.reply({'service': 'gpuq', 'owner': pwd.getpwuid(os.getuid()).pw_name, 'uid': os.getuid()})
                if path == '/api/host':
                    if not hasattr(self.server, 'host_monitor'):
                        self.server.host_monitor = HostMonitor()
                    return self.reply(self.server.host_monitor.state())
                if path == '/api/state':
                    return self.reply(self.server.control.state())
                asset = ASSETS.get(path)
                if asset:
                    return self.reply((self.server.assets/asset[0]).read_bytes(), content_type=asset[1])
                return self.reply({'error':'入口不存在'}, 404)
            if self.headers.get('Origin') != 'http://'+host or self.headers.get('X-GPUQ-Action') != '1' or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.reply({'error':'请在任务网页中操作'}, 403)
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                return self.reply({'error':'请求格式无效'}, 400)
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 16384 or self.headers.get('Transfer-Encoding'):
                return self.reply({'error':'请求大小无效'}, 400)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                return self.reply({'error':'请求格式无效'}, 400)
            match = re.fullmatch(r'/api/tasks/(GQ-[a-f0-9]{16})/start', path)
            if match:
                return self.reply(self.server.control.start(match[1], data.get('digest')))
            match = re.fullmatch(r'/api/tasks/(GQ-[a-f0-9]{16})/stop', path)
            if match:
                return self.reply(self.server.control.stop(match[1], data.get('digest')))
            match = re.fullmatch(r'/api/tasks/(GQ-[a-f0-9]{16})/delete', path)
            if match:
                return self.reply(self.server.control.delete(match[1], data.get('digest')))
            if path == '/api/tasks/cleanup':
                return self.reply(self.server.control.cleanup(data.get('ids'), data.get('revision')))
            if path == '/api/queue/reorder':
                return self.reply(self.server.control.reorder(data.get('ids'), data.get('revision')))
            return self.reply({'error':'入口不存在'}, 404)
        except ControlError as error:
            self.reply({'error':str(error)}, error.status)
        except (ValueError, json.JSONDecodeError):
            self.reply({'error':'请求格式无效'}, 400)
        except Exception:
            self.reply({'error':'任务服务暂时无法处理，请稍后重试'}, 500)

class Server(socketserver.UnixStreamServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address

def serve(store=None, socket_path=SOCKET):
    os.umask(0o077)
    socket_path = Path(socket_path)
    directory = socket_path.parent
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('网页 socket 目录必须是本人的 0700 私有目录')
    lock = (directory/'web.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    if socket_path.exists() or socket_path.is_symlink():
        info = socket_path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('拒绝覆盖未知 socket 路径')
        socket_path.unlink()
    with Server(str(socket_path), Handler) as server:
        os.chmod(socket_path, 0o600)
        server.control = Control(store)
        server.assets = Path(__file__).resolve().parent.parent/'web'
        print('GPU queue web ready on private SSH socket.', flush=True)
        server.serve_forever()
