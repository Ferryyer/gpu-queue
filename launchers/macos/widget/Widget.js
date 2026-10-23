/* macOS JavaScript for Automation / AppKit; prefixed with model.js at packaging. */
ObjC.import('Cocoa');
var widget, panel, target, labels = {}, buttons = {}, timer, nextUpdateCheck = 0, updateChecking = false;
var app = $.NSApplication.sharedApplication;
var home = ObjC.unwrap($.NSHomeDirectory());
var stateDir = home + '/Library/Application Support/GPU Queue';
var interactionMode = 'edit';
var resources = ObjC.unwrap($.NSBundle.mainBundle.resourcePath);
function chooseConfig() {
    var picker = $.NSOpenPanel.openPanel;
    picker.title = '选择本人 SSH 配置';
    picker.message = '选择你原来登录服务器用的 config 文件';
    picker.canChooseFiles = true; picker.canChooseDirectories = false;
    picker.allowsMultipleSelection = false; picker.showsHiddenFiles = true;
    picker.directoryURL = $.NSURL.fileURLWithPath(home + '/.ssh');
    if (picker.runModal !== $.NSModalResponseOK) return '';
    var path = text(picker.URL.path);
    if (/PRIVATE KEY/.test(readFile(path))) {
        var alert = $.NSAlert.alloc.init;
        alert.messageText = '请选择 SSH 配置文件';
        alert.informativeText = '这里需要 config 文件。'; alert.runModal;
        return '';
    }
    writeFile(stateDir + '/ssh-config-path', path); return path;
}
function config() {
    var candidates = [readFile(stateDir + '/ssh-config-path'), home + '/.ssh/markflow-linlishuo/config', home + '/.ssh/config'];
    for (var i = 0; i < candidates.length; i++) {
        if (candidates[i] && $.NSFileManager.defaultManager.fileExistsAtPath(candidates[i]) && !/PRIVATE KEY/.test(readFile(candidates[i]))) return candidates[i];
    }
    return chooseConfig();
}
function label(value, x, y, w, h, size, bold) {
    var field = $.NSTextField.alloc.initWithFrame($.NSMakeRect(x, y, w, h));
    field.stringValue = value; field.editable = false; field.selectable = false;
    field.bezeled = false; field.drawsBackground = false;
    field.font = bold ? ($.NSFont.fontWithNameSize('Charter',size) || $.NSFont.boldSystemFontOfSize(size)) : $.NSFont.systemFontOfSize(size);
    field.textColor = $.NSColor.colorWithSRGBRedGreenBlueAlpha(.19,.18,.17,1);
    field.cell.lineBreakMode = $.NSLineBreakByTruncatingTail;
    panel.contentView.addSubview(field); return field;
}
function button(title, action, x, y, w, h) {
    var b = $.NSButton.alloc.initWithFrame($.NSMakeRect(x, y, w, h));
    b.title = title; b.bezelStyle = $.NSBezelStyleRounded;
    b.target = target; b.action = action;
    panel.contentView.addSubview(b); return b;
}
function render(view) {
    if (!panel) return;
    var online = view.phase === 'online', busy = ['connecting', 'discovering', 'login'].indexOf(view.phase) >= 0;
    labels.status.stringValue = online ? '● 已连接' : busy ? '◷ 正在连接' : view.phase === 'auth' ? '◷ 等待登录' : '○ 未连接';
    labels.status.textColor = online ? $.NSColor.colorWithSRGBRedGreenBlueAlpha(.16,.43,.33,1) : $.NSColor.colorWithSRGBRedGreenBlueAlpha(.45,.43,.40,1);
    labels.note.stringValue = view.note;
    var s = view.summary;
    labels.stats.stringValue = s ? '运行 ' + s.running + '    排队 ' + s.queued + '    待启动 ' + s.ready : '运行 —    排队 —    待启动 —';
    labels.current.stringValue = s ? s.current : '连接后显示任务进度';
    labels.current.toolTip = s ? s.current : '';
    labels.attention.stringValue = s && s.attention ? s.attention + ' 个任务需要处理' : '只管理网页连接，任务由服务器执行';
    buttons.open.enabled = online;
    buttons.connect.title = view.owned ? '断开连接' : online ? '已有连接' : view.phase === 'auth' ? '完成登录' : '连接';
    buttons.connect.enabled = view.owned || (!online && !busy);
    buttons.connect.toolTip = online && !view.owned ? '连接由原启动器维护，关闭原连接窗口可断开' : '';
}
function renderInteractionMode() {
    buttons.mode.title = interactionMode === 'auto' ? 'Auto mode   ⇧⇥' : 'Edit mode   ⇧⇥';
    labels.modeHint.stringValue = interactionMode === 'auto' ? '打开网页监看已授权队列，不启动新任务' : '打开网页后可启动任务、调整队列';
    buttons.open.title = interactionMode === 'auto' ? '打开 Auto 监看' : '打开 Edit 任务台';
}
function safeTick() {
    try { pump(); widget.tick(); checkUpdates(); }
    catch (error) { labels.note.stringValue = '组件暂时无法更新，请关闭后重新打开'; }
}
function checkUpdates() {
    if (updateChecking || Date.now() < nextUpdateCheck) return;
    updateChecking = true; nextUpdateCheck = Date.now() + 6 * 3600000;
    try {
        process('/usr/bin/curl', ['--fail','--silent','--show-error','--location','--proto','=https','--proto-redir','=https',
            '--connect-timeout','10','--max-time','20','--max-filesize','65536',GPUQUpdates.feed + '?t=' + Date.now()], function (code, out) {
            updateChecking = false;
            if (code) return;
            try {
                var release = GPUQUpdates.manifest(JSON.parse(out));
                if (GPUQUpdates.compare(release.version, GPUQ_RELEASE_VERSION) > 0) {
                    buttons.update.title = '有更新 ' + release.version;
                    buttons.update.toolTip = '点击查看更新说明并安装';
                }
            } catch (ignored) {}
        });
    } catch (error) { updateChecking = false; }
}
function cleanupWidget() {
    if (timer) timer.invalidate;
    if (widget) widget.close();
    jobs.forEach(function (job) { if (job.task.running) job.task.terminate; removeJobFiles(job); });
    jobs = [];
}
function closeWidget() {
    cleanupWidget(); app.terminate(null);
}
ObjC.registerSubclass({name:'GPUQDesktopActions', superclass:'NSObject', protocols:['NSWindowDelegate'], methods:{
    'applicationExiting:': {types:['void',['id']], implementation:function () { cleanupWidget(); }},
    'tick:': {types:['void',['id']], implementation:function () { safeTick(); }},
    'openQueue:': {types:['void',['id']], implementation:function () {
        $.NSWorkspace.sharedWorkspace.openURL($.NSURL.URLWithString(GPUQWidget.queueURL(widget.port, interactionMode)));
    }},
    'toggleMode:': {types:['void',['id']], implementation:function () {
        interactionMode = interactionMode === 'edit' ? 'auto' : 'edit';
        writeFile(stateDir + '/interaction-mode', interactionMode);
        renderInteractionMode();
    }},
    'toggleConnection:': {types:['void',['id']], implementation:function () {
        if (widget.handle) widget.disconnect(); else widget.connect();
    }},
    'selectConfig:': {types:['void',['id']], implementation:function () {
        if (chooseConfig()) { widget.disconnect(); widget.phase = 'offline'; widget.connect(); }
    }},
    'pinPanel:': {types:['void',['id']], implementation:function (sender) {
        panel.level = sender.state === $.NSControlStateValueOn ? $.NSFloatingWindowLevel : -1;
    }},
    'showUpdates:': {types:['void',['id']], implementation:function () {
        var helper = text($.NSBundle.mainBundle.bundlePath) + '/Contents/Helpers/GPU 任务台更新器.app';
        if (!$.NSWorkspace.sharedWorkspace.openFile(helper)) {
            var alert = $.NSAlert.alloc.init;
            alert.messageText = '暂时无法打开更新窗口';
            alert.informativeText = '请重新安装最新的小组件安装包。'; alert.runModal;
        }
    }},
    'windowWillClose:': {types:['void',['id']], implementation:function () { closeWidget(); }}
}});
function run() {
    if (panel) { panel.orderFrontRegardless; return; }
    $.NSFileManager.defaultManager.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(stateDir, true, $({NSFilePosixPermissions:448}), null);
    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
    target = $.GPUQDesktopActions.alloc.init;
    $.NSNotificationCenter.defaultCenter.addObserverSelectorNameObject(target, 'applicationExiting:', $.NSApplicationWillTerminateNotification, null);
    panel = $.NSPanel.alloc.initWithContentRectStyleMaskBackingDefer($.NSMakeRect(0,0,344,340),
        $.NSWindowStyleMaskTitled | $.NSWindowStyleMaskClosable | $.NSWindowStyleMaskNonactivatingPanel,
        $.NSBackingStoreBuffered, false);
    panel.backgroundColor = $.NSColor.colorWithSRGBRedGreenBlueAlpha(.96,.95,.93,1);
    panel.title = 'GPU 任务台'; panel.titlebarAppearsTransparent = true;
    panel.titleVisibility = $.NSWindowTitleHidden;
    panel.hidesOnDeactivate = false; panel.floatingPanel = false;
    panel.becomesKeyOnlyIfNeeded = true; panel.movableByWindowBackground = true;
    panel.releasedWhenClosed = false; panel.delegate = target;
    panel.level = -1;
    panel.collectionBehavior = $.NSWindowCollectionBehaviorCanJoinAllSpaces | $.NSWindowCollectionBehaviorStationary;
    panel.setFrameAutosaveName('GPUQueueDesktopPanel');
    if (!panel.setFrameUsingName('GPUQueueDesktopPanel')) {
        var screen = $.NSScreen.mainScreen.visibleFrame;
        panel.setFrameOrigin($.NSMakePoint(screen.origin.x + screen.size.width - 368, screen.origin.y + screen.size.height - 310));
    }
    panel.setContentSize($.NSMakeSize(344,340));
    interactionMode = GPUQWidget.interactionMode(readFile(stateDir + '/interaction-mode'));
    label('GPU 任务台',20,292,220,30,23,true);
    labels.status = label('○ 未连接',22,267,294,20,12,true);
    labels.note = label('正在检查已有连接…',22,246,298,18,11,false);
    labels.note.textColor = $.NSColor.colorWithSRGBRedGreenBlueAlpha(.45,.43,.40,1);
    labels.stats = label('运行 —    排队 —    待启动 —',20,206,304,27,17,true);
    labels.current = label('连接后显示任务进度',22,180,298,21,12,false);
    buttons.mode = button('Edit mode   ⇧⇥','toggleMode:',16,140,180,30);
    buttons.mode.keyEquivalent = '\t';
    buttons.mode.keyEquivalentModifierMask = $.NSEventModifierFlagShift;
    buttons.mode.toolTip = 'Shift+Tab 切换下次打开网页的模式；不修改已打开的网页';
    labels.modeHint = label('',22,112,300,22,11,false);
    buttons.open = button('打开任务台', 'openQueue:',16,69,188,34);
    buttons.connect = button('连接','toggleConnection:',207,69,120,34);
    button('SSH 配置','selectConfig:',16,31,100,28);
    buttons.update = button('检查更新','showUpdates:',114,31,144,28);
    buttons.update.toolTip = '当前版本 ' + GPUQ_RELEASE_VERSION;
    var pin = button('置顶','pinPanel:',259,33,70,25);
    pin.setButtonType($.NSButtonTypeSwitch);
    labels.attention = label('只管理网页连接，任务由服务器执行',22,8,300,18,10,false);
    labels.attention.textColor = $.NSColor.colorWithSRGBRedGreenBlueAlpha(.45,.43,.40,1);
    widget = new GPUQWidget.Controller({
        now:function () { return Date.now(); },
        render:render,
        savedPort:function () { return readFile(stateDir + '/port'); },
        savePort:function (p) { writeFile(stateDir + '/port',p); },
        config:config,
        http:function (p,path,done) {
            process('/usr/bin/curl',['--noproxy','*','--connect-timeout','1','--max-time','3','--fail','--silent','http://127.0.0.1:'+p+path],function (code,out) {
                var value = null; try { value = JSON.parse(out); } catch (error) {}
                done(code || !value, value);
            });
        },
        ssh:function (args,done) {
            return process('/usr/bin/ssh', args, function (code,out,err) { done(err || (code ? 'SSH disconnected' : 'Connection closed')); });
        },
        stop:function (handle) { if (handle.task.running) handle.task.terminate; },
        login:function () {
            $.NSWorkspace.sharedWorkspace.openFileWithApplication(resources + '/Open-GPU-Queue.command', 'Terminal');
        }
    });
    renderInteractionMode();
    panel.orderFrontRegardless;
    timer = $.NSTimer.scheduledTimerWithTimeIntervalTargetSelectorUserInfoRepeats(1, target, 'tick:', null, true);
    widget.connect();
}
function reopen() { if (panel) panel.orderFrontRegardless; else run(); }
