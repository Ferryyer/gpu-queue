/* Shared, platform-independent connection state machine. */
var GPUQWidget = (function () {
    function interactionMode(value) { return value === 'auto' ? 'auto' : 'edit'; }
    function queueURL(port, mode) {
        if (!Number.isInteger(Number(port)) || Number(port) < 8790 || Number(port) > 8799) throw new Error('Invalid local port');
        return 'http://127.0.0.1:' + Number(port) + '/?mode=' + interactionMode(mode);
    }
    function identity(data) {
        return data && data.service === 'gpuq' && data.owner === 'linlishuo' && data.uid === 21005;
    }
    function counts(tasks) {
        var result = {running: 0, queued: 0, ready: 0, attention: 0, current: '暂无正在运行的任务'};
        var running = ['running', 'starting', 'dispatching', 'stopping'];
        var queued = ['queued', 'waiting_gpu', 'checking_resources'];
        (tasks || []).forEach(function (t) {
            if (running.indexOf(t.state) >= 0) {
                if (!result.running) result.current = t.name || '正在执行任务';
                result.running++;
            } else if (queued.indexOf(t.state) >= 0) result.queued++;
            else if (t.state === 'ready') result.ready++;
            else if (['failed', 'blocked', 'interrupted', 'execution_unknown'].indexOf(t.state) >= 0) result.attention++;
        });
        return result;
    }
    function sshArgs(config, port) {
        return ['-F', config, '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3',
            '-L', '127.0.0.1:' + port + ':/tmp/gpuq-21005/web.sock', 'markflow-cpu'];
    }
    function Controller(io) {
        this.io = io;
        this.epoch = 0;
        this.handle = null;
        this.phase = 'offline';
        this.port = 8790;
        this.data = null;
        this.note = '点击连接，即可查看任务进度';
        this.pending = false;
        this.next = 0;
        this.mode = 'health';
        this.discover = [];
        this.connectingAt = 0;
    }
    Controller.prototype.view = function () {
        return {phase: this.phase, port: this.port, note: this.note,
            owned: !!this.handle, summary: this.data ? counts(this.data.tasks) : null};
    };
    Controller.prototype.render = function () { this.io.render(this.view()); };
    Controller.prototype.connect = function () {
        if (this.phase === 'online' || this.phase === 'connecting') return;
        if (this.phase === 'auth') {
            this.io.login();
            this.phase = 'login'; this.connectingAt = this.io.now();
            this.note = '请在登录窗口完成原有 SSH 登录';
            this.next = 0;
            this.render();
            return;
        }
        this.epoch++;
        this.phase = 'discovering';
        this.note = '正在检查已有连接…';
        var saved = Number(this.io.savedPort());
        this.discover = [];
        if (saved >= 8790 && saved <= 8799 && saved % 1 === 0) this.discover.push(saved);
        for (var p = 8790; p <= 8799; p++) if (this.discover.indexOf(p) < 0) this.discover.push(p);
        this.mode = 'health'; this.next = 0; this.pending = false;
        this.render();
        this.tick();
    };
    Controller.prototype.begin = function (port) {
        var self = this, config = this.io.config();
        if (!config) {
            this.phase = 'offline'; this.note = '尚未选择 SSH 配置'; this.render(); return;
        }
        this.port = port;
        this.phase = 'connecting'; this.note = '正在连接你的服务器…';
        this.connectingAt = this.io.now(); this.next = 0; this.mode = 'health';
        var epoch = this.epoch;
        this.handle = this.io.ssh(sshArgs(config, port), function (error) {
            if (epoch !== self.epoch) return;
            self.handle = null;
            // Invalidate in-flight HTTP replies from the exited tunnel.
            self.epoch++; self.pending = false;
            if (/Address already in use|cannot listen|Could not request local forwarding/.test(error) && port < 8799) {
                self.begin(port + 1); return;
            }
            self.phase = /Permission denied|Host key verification failed|passphrase|Authentication|sign_and_send_pubkey|Too many authentication/.test(error) ? 'auth' : 'error';
            self.data = null;
            self.note = self.phase === 'auth' ? '需要本人 SSH 登录，点击“完成登录”' : '连接已断开，点击连接重试';
            self.render();
        });
        this.render();
    };
    Controller.prototype.disconnect = function () {
        // Only terminate a child created by this widget, never another tunnel.
        if (!this.handle) return;
        this.epoch++; this.pending = false;
        var handle = this.handle; this.handle = null; this.io.stop(handle);
        this.phase = 'offline'; this.data = null; this.note = '网页连接已断开，服务器任务继续运行';
        this.render();
    };
    Controller.prototype.close = function () {
        this.disconnect(); this.epoch++; this.phase = 'closed';
    };
    Controller.prototype.tick = function () {
        var self = this;
        if (this.pending || this.io.now() < this.next) return;
        if (['discovering', 'connecting', 'online', 'login'].indexOf(this.phase) < 0) return;
        if (this.phase === 'login' && this.io.now() - this.connectingAt > 180000) {
            this.phase = 'auth'; this.note = '登录尚未完成，点击完成登录重试'; this.render(); return;
        }
        if (this.phase === 'connecting' && this.io.now() - this.connectingAt > 180000) {
            this.disconnect(); this.phase = 'error'; this.note = '网页暂未响应，稍后点击连接重试'; this.render(); return;
        }
        if (this.phase === 'discovering' && !this.discover.length) { this.begin(8790); return; }
        var port = this.phase === 'discovering' ? this.discover.shift() : this.port;
        var path = this.mode === 'state' ? '/api/state' : '/api/health';
        var epoch = this.epoch;
        this.pending = true;
        this.io.http(port, path, function (error, data) {
            if (epoch !== self.epoch) return;
            self.pending = false;
            self.next = self.io.now() + (self.phase === 'online' ? 5000 : 100);
            if (path === '/api/health' && !error && identity(data)) {
                self.port = port; self.phase = 'online'; self.mode = 'state'; self.next = 0;
                self.note = self.handle ? '已连接 · 由小组件保持' : '已连接 · 复用已有连接';
                self.io.savePort(port); self.render(); return;
            }
            if (path === '/api/state' && !error && data && Array.isArray(data.tasks)) {
                self.data = data;
                self.note = data.heartbeat && data.heartbeat.error ? '队列服务需要核查，打开任务台查看' : (self.handle ? '已连接 · 由小组件保持' : '已连接 · 复用已有连接');
                self.render(); return;
            }
            self.data = null; self.mode = 'health';
            if (self.phase === 'online') {
                self.phase = self.handle ? 'connecting' : 'offline';
                self.connectingAt = self.io.now();
                self.note = self.handle ? '连接暂时中断，正在检查…' : '原有连接已断开，点击连接重试';
            }
            if (self.phase === 'login') self.port = port === 8799 ? 8790 : port + 1;
            self.render();
        });
    };
    return {interactionMode: interactionMode, queueURL: queueURL, identity: identity, counts: counts, sshArgs: sshArgs, Controller: Controller};
}());
if (typeof module !== 'undefined') module.exports = GPUQWidget;
