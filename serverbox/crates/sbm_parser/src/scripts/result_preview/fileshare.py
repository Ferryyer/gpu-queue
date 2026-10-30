#!/usr/bin/env python3
"""只读文件分享：Agent 登记文件，用户经 SSH 转发在本地浏览器预览或下载。

服务只监听本人私有目录下的 Unix socket，只提供已登记的文件或目录。
"""
import argparse
import fcntl
import html
import json
import mimetypes
import os
import re
import secrets
import socket
import socketserver
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler

HOME = os.path.realpath(os.path.expanduser("~"))
UID = os.getuid()
SOCK_DIR = os.environ.get("FSHARE_SOCK_DIR", f"/tmp/fileshare-{UID}")
SOCK_PATH = os.path.join(SOCK_DIR, "web.sock")
STATE_DIR = os.environ.get("FSHARE_STATE_DIR", os.path.join(HOME, ".local/state/fileshare"))
REGISTRY = os.path.join(STATE_DIR, "links.json")
LOCAL_PORT = int(os.environ.get("FSHARE_PORT", "8780"))
BASE_URL = f"http://127.0.0.1:{LOCAL_PORT}"
CHUNK = 1 << 20

DENY_DIRS = {".ssh", ".gnupg", ".config", ".codex", ".claude", ".aws", ".kube",
             ".docker", ".lark-cli", ".markflow-editor", ".password-store"}
DENY_NAME = re.compile(r"(^\.env|\.env$|\.pem$|\.key$|^id_[a-z0-9]+|^\.netrc$|"
                       r"^\.git-credentials$|credential|secret|^tokens?(\.|$))", re.I)
TEXT_EXT = {".py", ".md", ".log", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml",
            ".sh", ".csv", ".tsv", ".ini", ".cfg", ".js", ".ts", ".c", ".cpp", ".h",
            ".rs", ".go", ".java", ".tex", ".err", ".out"}

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("image/webp", ".webp")


def denied(path):
    """凭据类路径一律不分享，目录分享中的子路径同样检查。"""
    parts = os.path.realpath(path).split(os.sep)
    if any(p in DENY_DIRS for p in parts):
        return True
    return any(DENY_NAME.search(p) for p in parts if p)


def load_registry():
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_registry(reg):
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    tmp = f"{REGISTRY}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, REGISTRY)


def share_url(token, entry, sub=""):
    name = urllib.parse.quote(entry["name"])
    url = f"{BASE_URL}/f/{token}/{name}"
    return url + "/" + urllib.parse.quote(sub) if sub else url


def add(paths, name=None):
    reg = load_registry()
    out = []
    for p in paths:
        real = os.path.realpath(p)
        if not os.path.exists(real):
            raise SystemExit(f"不存在：{p}")
        if denied(real):
            raise SystemExit(f"拒绝分享凭据类路径：{p}")
        token = next((t for t, e in reg.items() if e["path"] == real), None)
        if token is None:
            token = secrets.token_urlsafe(9)
            reg[token] = {"path": real, "created": int(time.time()),
                          "kind": "dir" if os.path.isdir(real) else "file"}
        reg[token]["name"] = (name if name and len(paths) == 1 else os.path.basename(real)) or "root"
        out.append((token, reg[token]))
    save_registry(reg)
    return out


def remove(keys):
    reg = load_registry()
    n = 0
    for k in keys:
        real = os.path.realpath(k)
        for t in [t for t, e in reg.items() if t == k or e["path"] == real]:
            del reg[t]
            n += 1
    save_registry(reg)
    return n


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title}</title><style>
body{{font:15px system-ui,sans-serif;margin:2rem auto;max-width:960px;padding:0 1rem;background:#faf7f0;color:#222}}
h1{{font-family:Georgia,serif;font-weight:500}} table{{border-collapse:collapse;width:100%}}
td{{padding:.45rem .5rem;border-bottom:1px solid #e5dfd2;vertical-align:middle}}
a{{color:#7a3e12}} .m{{color:#777;font-size:13px}} img.t{{max-height:64px;max-width:120px}}
</style><h1>{title}</h1>{body}"""


class Handler(BaseHTTPRequestHandler):
    server_version = "fshare"

    def address_string(self):
        return "unix"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%F %T"), fmt % args))

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost", "[::1]"):
            return self.fail(403, "只接受本机地址访问")
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        parts = [urllib.parse.unquote(p) for p in url.path.split("/") if p]
        if not parts:
            return self.index(head)
        if parts[0] != "f" or len(parts) < 3:
            return self.fail(404, "未找到")
        entry = load_registry().get(parts[1])
        if entry is None:
            return self.fail(404, "链接不存在或已移除")
        root = entry["path"]
        target = os.path.realpath(os.path.join(root, *parts[3:]))
        if target != root and not target.startswith(root + os.sep):
            return self.fail(403, "越界路径")
        if denied(target):
            return self.fail(403, "凭据类路径不提供")
        if os.path.isdir(target):
            return self.listing(parts[1], entry, target, head)
        if not os.path.isfile(target):
            return self.fail(404, "文件已不存在")
        self.send_file(target, "dl" in query, head)

    def fail(self, code, msg):
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def page(self, title, body, head):
        data = PAGE.format(title=html.escape(title), body=body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def row(self, url, label, path, isdir):
        esc = html.escape
        thumb = ""
        mime = mimetypes.guess_type(path)[0] or ""
        if mime.startswith("image/"):
            thumb = f'<img class="t" src="{esc(url)}" loading="lazy">'
        size = "目录" if isdir else (human(os.path.getsize(path)) if os.path.exists(path) else "已删除")
        dl = "" if isdir else f' · <a href="{esc(url)}?dl=1">下载</a>'
        return (f'<tr><td>{thumb}</td><td><a href="{esc(url)}">{esc(label)}</a>{dl}'
                f'<div class="m">{esc(path)}</div></td><td class="m">{size}</td></tr>')

    def index(self, head):
        reg = load_registry()
        rows = [self.row(share_url(t, e), e["name"], e["path"], e["kind"] == "dir")
                for t, e in sorted(reg.items(), key=lambda kv: -kv[1]["created"])]
        body = f"<table>{''.join(rows)}</table>" if rows else "<p>暂无分享。服务器上运行 <code>fshare 文件</code> 登记。</p>"
        self.page("已分享文件", body, head)

    def listing(self, token, entry, target, head):
        rel = os.path.relpath(target, entry["path"])
        rel = "" if rel == "." else rel
        rows = []
        if rel:
            up = os.path.dirname(rel)
            rows.append(f'<tr><td></td><td><a href="{html.escape(share_url(token, entry, up) + "/")}">..</a></td><td></td></tr>')
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            if name.startswith(".") or denied(full):
                continue
            isdir = os.path.isdir(full)
            url = share_url(token, entry, os.path.join(rel, name)) + ("/" if isdir else "")
            rows.append(self.row(url, name + ("/" if isdir else ""), full, isdir))
        self.page(os.path.join(entry["name"], rel), f"<p><a href='/'>全部分享</a></p><table>{''.join(rows)}</table>", head)

    def send_file(self, path, download, head):
        size = os.path.getsize(path)
        ext = os.path.splitext(path)[1].lower()
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ext in {'.js', '.mjs'}:
            mime = 'text/javascript; charset=utf-8'
        elif ext == '.css':
            mime = 'text/css; charset=utf-8'
        elif ext in TEXT_EXT or mime.startswith("text/"):
            mime = ("text/html" if mime == "text/html" else "text/plain") + "; charset=utf-8"
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(size - int(m.group(2)), 0)
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        # 分享的网页在独立来源中运行，不能读取其他分享或索引页
        self.send_header("Content-Security-Policy", "sandbox allow-scripts allow-popups allow-forms")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        disp = "attachment" if download else "inline"
        self.send_header("Content-Disposition",
                         f"{disp}; filename*=UTF-8''{urllib.parse.quote(os.path.basename(path))}")
        self.end_headers()
        if head:
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    buf = f.read(min(CHUNK, left))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    left -= len(buf)
            except (BrokenPipeError, ConnectionResetError):
                pass


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve():
    os.umask(0o077)
    os.makedirs(SOCK_DIR, mode=0o700, exist_ok=True)
    os.chmod(SOCK_DIR, 0o700)
    with open(os.path.join(SOCK_DIR, 'service.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.path.exists(SOCK_PATH):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(2)
            try:
                probe.connect(SOCK_PATH)
                raise RuntimeError('成果连接已由其他服务使用')
            except ConnectionRefusedError:
                os.unlink(SOCK_PATH)
            finally:
                probe.close()
        with Server(SOCK_PATH, Handler) as srv:
            os.chmod(SOCK_PATH, 0o600)
            print(f"listening on {SOCK_PATH}", flush=True)
            srv.serve_forever()


def ssh_hint():
    return (f"在 Inspire Queue 的服务器详情中打开「端口映射 → 打开成果链接」。\n"
            f"全部成果：{BASE_URL}/")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] not in ("add", "list", "rm", "serve", "hint", "-h", "--help"):
        argv = ["add"] + argv
    ap = argparse.ArgumentParser(prog="fshare", description="登记文件并生成本地预览/下载链接")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="登记文件或目录（默认命令）")
    a.add_argument("paths", nargs="+")
    a.add_argument("--name", help="单个文件时自定义显示名")
    sub.add_parser("list", help="列出已登记")
    r = sub.add_parser("rm", help="按 token 或路径移除")
    r.add_argument("keys", nargs="+")
    sub.add_parser("serve", help="前台运行服务")
    sub.add_parser("hint", help="显示 SSH 转发命令")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        serve()
    elif args.cmd == "add":
        for token, e in add(args.paths, args.name):
            url = share_url(token, e) + ("/" if e["kind"] == "dir" else "")
            print(f"{e['name']}\n  预览：{url}" + ("" if e["kind"] == "dir" else f"\n  下载：{url}?dl=1"))
        if not os.path.exists(SOCK_PATH):
            print("警告：服务未运行（mf-services status 查看 fileshare）", file=sys.stderr)
    elif args.cmd == "list":
        for t, e in sorted(load_registry().items(), key=lambda kv: kv[1]["created"]):
            print(f"{t}  {e['path']}\n    {share_url(t, e)}")
    elif args.cmd == "rm":
        print(f"已移除 {remove(args.keys)} 项")
    elif args.cmd == "hint":
        print(ssh_hint())


if __name__ == "__main__":
    main()
