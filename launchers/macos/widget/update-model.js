/* ES5, shared by the desktop panel, native updater and CPU tests. */
var GPUQUpdates = (function () {
    var feed = 'https://raw.githubusercontent.com/Ferryyer/Ferryyer/main/updates/gpu-queue-widget.json';
    var prefix = 'https://raw.githubusercontent.com/Ferryyer/Ferryyer/main/downloads/';
    function version(value) {
        if (typeof value !== 'string' || value !== value.trim() || !/^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$/.test(value)) throw new Error('版本号无效');
        return value.split('.').map(function (part) { return Number(part); });
    }
    function compare(a, b) {
        a = version(a); b = version(b);
        for (var i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i] ? 1 : -1;
        return 0;
    }
    function manifest(data) {
        if (!data || data.schema !== 1) throw new Error('更新信息格式不受支持');
        version(data.version);
        if (data.url !== prefix + 'GPU-Queue-Widget-' + data.version + '-macOS.zip') throw new Error('更新下载地址不受信任');
        if (typeof data.sha256 !== 'string' || data.sha256.length !== 64 || !/^[0-9a-f]{64}$/.test(data.sha256)) throw new Error('更新文件校验信息无效');
        if (typeof data.bytes !== 'number' || data.bytes % 1 || data.bytes <= 0 || data.bytes > 20 * 1024 * 1024) throw new Error('更新文件大小无效');
        if (!Array.isArray(data.notes) || data.notes.length > 20 || data.notes.some(function (n) { return typeof n !== 'string' || n.length > 1000; })) throw new Error('更新说明无效');
        return {version:data.version, url:data.url, sha256:data.sha256, bytes:data.bytes, notes:data.notes.slice()};
    }
    var files = ['安装桌面小组件.command', '开启开机自启动.command', '关闭开机自启动.command', 'Autostart.command',
        'Widget.bundle.js', 'Updater.bundle.js', 'VERSION', 'Open-GPU-Queue.command', '使用说明.txt'];
    function archiveEntries(list) {
        // Info-ZIP may print Unicode names as #Uxxxx / #Lxxxxxx when the
        // Finder-launched updater has no UTF-8 locale. Decode only that documented
        // display format, then retain the exact whitelist and duplicate checks.
        var entries = list.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n').map(function (entry) {
            return entry.replace(/#(?:U([0-9a-fA-F]{4})|L([0-9a-fA-F]{6}))/g, function (escape, short, long) {
                var code = parseInt(short || long, 16);
                if (code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) throw new Error('安装包文件路径无效');
                if (code <= 0xffff) return String.fromCharCode(code);
                code -= 0x10000;
                return String.fromCharCode(0xd800 + (code >> 10), 0xdc00 + (code & 1023));
            });
        });
        var expected = files.map(function (name) { return 'GPU任务台桌面小组件/' + name; });
        if (entries.length !== expected.length) throw new Error('安装包文件清单不符');
        expected.forEach(function (path) {
            if (entries.filter(function (entry) { return entry === path; }).length !== 1) throw new Error('安装包文件路径无效');
        });
    }
    function archiveMetadata(list) {
        var entries = list.split('\n').filter(function (line) { return /^[bcdlps-][rwxstST-]{9}\s/.test(line); });
        var total = 0;
        if (entries.length !== files.length) throw new Error('安装包文件属性无效');
        entries.forEach(function (line) {
            var size = Number(line.trim().split(/\s+/)[3]);
            if (line.charAt(0) !== '-' || !isFinite(size) || size < 0 || size % 1 || size > 4 * 1024 * 1024) throw new Error('安装包包含不支持的文件');
            total += size;
        });
        if (total > 16 * 1024 * 1024) throw new Error('安装包展开后过大');
    }
    function Controller(io, current) {
        version(current); this.io = io; this.current = current; this.phase = 'idle';
        this.release = null; this.note = ''; this.epoch = 0; this.deadline = 0;
    }
    Controller.prototype.busy = function () {
        return ['checking','downloading','verifying','extracting','preparing','waiting','installing'].indexOf(this.phase) >= 0;
    };
    Controller.prototype.emit = function () { this.io.render(this); };
    Controller.prototype.fail = function (message) {
        this.epoch++; this.io.cancel(); this.phase = 'error'; this.note = String(message); this.emit();
    };
    Controller.prototype.check = function () {
        if (this.busy()) return;
        var self = this, token = ++this.epoch;
        this.phase = 'checking'; this.note = '正在检查 GitHub 上的新版本…'; this.release = null; this.emit();
        try {
            this.io.fetch(function (error, data) {
                if (token !== self.epoch) return;
                if (error) { self.fail('暂时无法连接 GitHub，请稍后重新检查。'); return; }
                try {
                    self.release = manifest(data);
                    self.phase = compare(self.release.version, self.current) > 0 ? 'available' : 'current';
                    self.note = self.phase === 'available' ? '有新版本可以安装' : '当前已是最新版本'; self.emit();
                } catch (e) { self.fail(e.message); }
            });
        } catch (e) { this.fail(e.message); }
    };
    Controller.prototype.install = function () {
        if (this.phase !== 'available') return;
        var self = this, token = ++this.epoch;
        var messages = {downloading:'正在下载安装包…', verifying:'正在校验下载文件…', extracting:'正在准备安装文件…', preparing:'正在生成新版小组件…'};
        function step(phase) {
            if (token !== self.epoch) return;
            self.phase = phase; self.note = messages[phase]; self.deadline = self.io.now() + 180000; self.emit();
            try {
                self.io.operation(phase, self.release, function (error) {
                    if (token !== self.epoch) return;
                    if (error) { self.fail(error); return; }
                    if (phase === 'preparing') {
                        if (self.phase !== 'installing') { self.fail('安装未完成，请重新检查更新。'); return; }
                        self.current = self.release.version;
                        self.phase = 'done'; self.note = '更新完成，小组件已重新打开。'; self.emit();
                    } else step({downloading:'verifying', verifying:'extracting', extracting:'preparing'}[phase]);
                });
            } catch (e) { self.fail(e.message); }
        }
        step('downloading');
    };
    Controller.prototype.tick = function () {
        if (this.phase === 'preparing' && this.io.ready()) {
            this.phase = 'waiting'; this.deadline = this.io.now() + 30000;
            this.note = '正在关闭旧版小组件，服务器任务继续运行…'; this.emit();
            try { this.io.quitWidget(); } catch (e) { this.fail(e.message); return; }
        }
        if (this.phase === 'waiting' && this.io.widgetStopped()) {
            try { this.io.permit(); } catch (e) { this.fail(e.message); return; }
            this.phase = 'installing'; this.deadline = this.io.now() + 60000;
            this.note = '正在安装并重新打开…'; this.emit();
        }
        if (this.busy() && this.phase !== 'checking' && this.io.now() > this.deadline) this.fail('更新超时，请重新打开小组件后重试。');
    };
    return {feed:feed, version:version, compare:compare, manifest:manifest, archiveEntries:archiveEntries, archiveMetadata:archiveMetadata, Controller:Controller};
}());
if (typeof module !== 'undefined') module.exports = GPUQUpdates;
