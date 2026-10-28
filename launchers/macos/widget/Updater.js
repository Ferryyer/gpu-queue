/* Runs in its own app so closing/replacing the widget cannot kill installation. */
ObjC.import('Cocoa');
var app = $.NSApplication.sharedApplication;
var home = text($.NSHomeDirectory());
var stateDir = home + '/Library/Application Support/GPU Queue';
var installed = home + '/Applications/GPU 任务台小组件.app';
var window, target, timer, controller, fields = {}, workDir = '', archive = '', unpacked = '';
var oldWidgets = [];
function matchingWidgets() {
    var matches = [], apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier('work.markflow.gpuqueue.widget.linlishuo');
    for (var i = 0; i < apps.count; i++) {
        var candidate = apps.objectAtIndex(i);
        if (!candidate.terminated && text(candidate.bundleURL.path) === installed) matches.push(candidate);
    }
    return matches;
}
function cancelJobs() {
    jobs.forEach(function (job) { if (job.task.running) job.task.terminate; removeJobFiles(job); });
    jobs = [];
}
function cleanWork() {
    if (workDir) $.NSFileManager.defaultManager.removeItemAtPathError(workDir, null);
    workDir = '';
}
function cleanupUpdater() {
    if (timer) timer.invalidate;
    cancelJobs(); cleanWork();
}
function finish() {
    if (controller && controller.busy()) return;
    cleanupUpdater(); app.terminate(null);
}
function command(path, args, done) {
    process(path, args, function (code, out, err) {
        if (code) {
            writeFile(stateDir + '/update-last-error.log', err + '\n' + out);
            done('更新未完成。可以重新打开小组件或稍后重试。');
        } else done(null, out);
    });
}
function zipListing(option, done) {
    // Finder does not reliably provide a UTF-8 locale. Do not inherit options
    // that could change the listing format used by the package validator.
    command('/usr/bin/env', ['LC_ALL=en_US.UTF-8','LANG=en_US.UTF-8',
        'ZIPINFO=','ZIPINFOOPT=','UNZIP=','UNZIPOPT=',
        '/usr/bin/unzip','-Z',option,archive], done);
}
function curl(url, output, maximum, done) {
    var args = ['--fail','--silent','--show-error','--location','--proto','=https','--proto-redir','=https',
        '--connect-timeout','10','--max-time',output ? '150' : '20','--max-filesize',String(maximum)];
    if (output) args.push('--output',output);
    args.push(url); command('/usr/bin/curl',args,done);
}
function operation(phase, release, done) {
    if (phase === 'downloading') {
        cleanWork();
        workDir = stateDir + '/update-' + text($.NSUUID.UUID.UUIDString);
        if (!$.NSFileManager.defaultManager.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(workDir, false, $({NSFilePosixPermissions:448}), null)) throw new Error('无法准备更新目录');
        archive = workDir + '/package.zip'; unpacked = workDir + '/unpacked';
        curl(release.url, archive, release.bytes, done);
    } else if (phase === 'verifying') {
        var data = $.NSData.dataWithContentsOfFile(archive);
        if (data.isNil() || Number(data.length) !== release.bytes) { done('下载文件不完整，请重新检查更新。'); return; }
        command('/usr/bin/shasum',['-a','256',archive],function (error,out) {
            if (error) done(error);
            else if (out.split(/\s+/)[0] !== release.sha256) done('下载文件校验不通过，请稍后重新检查更新。');
            else done(null);
        });
    } else if (phase === 'extracting') {
        zipListing('-1',function (error,out) {
            if (error) { done(error); return; }
            try { GPUQUpdates.archiveEntries(out); } catch (e) { done(e.message); return; }
            zipListing('-l',function (error,listing) {
                if (error) { done(error); return; }
                try { GPUQUpdates.archiveMetadata(listing); } catch (e) { done(e.message); return; }
                command('/usr/bin/ditto',['-x','-k',archive,unpacked],function (error) {
                    if (error) { done(error); return; }
                    if (readFile(unpacked + '/GPU任务台桌面小组件/VERSION') !== release.version) done('安装包版本与更新信息不一致。');
                    else done(null);
                });
            });
        });
    } else if (phase === 'preparing') {
        command('/bin/bash',[unpacked + '/GPU任务台桌面小组件/安装桌面小组件.command','--update',workDir],done);
    }
}
function renderUpdate(model) {
    var busy = model.busy();
    fields.current.stringValue = '当前版本  ' + model.current;
    fields.latest.stringValue = model.release ? '可用版本  ' + model.release.version : '通过 GitHub 获取更新';
    fields.status.stringValue = model.note;
    fields.status.toolTip = model.note;
    fields.notes.string = model.release ? model.release.notes.map(function (n) { return '• ' + n; }).join('\n\n') : '更新说明会显示在这里。';
    fields.install.enabled = model.phase === 'available';
    fields.check.enabled = !busy;
    fields.close.enabled = !busy;
    window.standardWindowButton($.NSWindowCloseButton).enabled = !busy;
    if (busy) fields.progress.startAnimation(null); else fields.progress.stopAnimation(null);
}
function tick() {
    try { pump(); controller.tick(); }
    catch (error) { controller.fail('暂时无法完成更新，请重新检查。'); }
}
ObjC.registerSubclass({name:'GPUQUpdaterActions', superclass:'NSObject', protocols:['NSWindowDelegate'], methods:{
    'tick:': {types:['void',['id']], implementation:tick},
    'check:': {types:['void',['id']], implementation:function () { controller.check(); }},
    'install:': {types:['void',['id']], implementation:function () { controller.install(); }},
    'close:': {types:['void',['id']], implementation:finish},
    'windowShouldClose:': {types:['BOOL',['id']], implementation:function () { return !controller || !controller.busy(); }},
    'windowWillClose:': {types:['void',['id']], implementation:finish},
    'applicationExiting:': {types:['void',['id']], implementation:cleanupUpdater}
}});
function label(value, x, y, w, h, size, bold) {
    var f = $.NSTextField.alloc.initWithFrame($.NSMakeRect(x,y,w,h));
    f.stringValue = value; f.editable = false; f.selectable = false; f.bezeled = false; f.drawsBackground = false;
    f.font = bold ? ($.NSFont.fontWithNameSize('Charter',size) || $.NSFont.boldSystemFontOfSize(size)) : $.NSFont.systemFontOfSize(size);
    f.textColor = $.NSColor.colorWithSRGBRedGreenBlueAlpha(.19,.18,.17,1);
    f.cell.lineBreakMode = $.NSLineBreakByTruncatingTail;
    window.contentView.addSubview(f); return f;
}
function button(title, action, x, w) {
    var b = $.NSButton.alloc.initWithFrame($.NSMakeRect(x,20,w,34));
    b.title = title; b.bezelStyle = $.NSBezelStyleRounded; b.target = target; b.action = action;
    window.contentView.addSubview(b); return b;
}
function run() {
    if (window) { window.makeKeyAndOrderFront(null); app.activateIgnoringOtherApps(true); return; }
    $.NSFileManager.defaultManager.createDirectoryAtPathWithIntermediateDirectoriesAttributesError(stateDir,true,$({NSFilePosixPermissions:448}),null);
    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
    target = $.GPUQUpdaterActions.alloc.init;
    $.NSNotificationCenter.defaultCenter.addObserverSelectorNameObject(target,'applicationExiting:',$.NSApplicationWillTerminateNotification,null);
    window = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer($.NSMakeRect(0,0,500,386),$.NSWindowStyleMaskTitled | $.NSWindowStyleMaskClosable,$.NSBackingStoreBuffered,false);
    window.appearance = $.NSAppearance.appearanceNamed($.NSAppearanceNameAqua);
    window.backgroundColor = $.NSColor.colorWithSRGBRedGreenBlueAlpha(.96,.95,.93,1);
    window.title = 'Inspire Queue · 软件更新'; window.releasedWhenClosed = false; window.delegate = target;
    label('软件更新',24,326,450,34,25,true);
    fields.current = label('',26,298,215,24,13,false);
    fields.latest = label('',248,298,226,24,13,false);
    var scroll = $.NSScrollView.alloc.initWithFrame($.NSMakeRect(26,132,448,154));
    scroll.hasVerticalScroller = true; scroll.borderType = $.NSBezelBorder;
    fields.notes = $.NSTextView.alloc.initWithFrame($.NSMakeRect(0,0,424,154));
    fields.notes.editable = false; fields.notes.selectable = true;
    fields.notes.textColor = $.NSColor.colorWithSRGBRedGreenBlueAlpha(.19,.18,.17,1);
    fields.notes.backgroundColor = $.NSColor.colorWithSRGBRedGreenBlueAlpha(.99,.98,.96,1);
    fields.notes.font = $.NSFont.systemFontOfSize(13);
    fields.notes.textContainerInset = $.NSMakeSize(10,10);
    fields.notes.verticallyResizable = true;
    fields.notes.textContainer.widthTracksTextView = true;
    scroll.documentView = fields.notes; window.contentView.addSubview(scroll);
    fields.status = label('',26,100,448,24,12,false);
    fields.progress = $.NSProgressIndicator.alloc.initWithFrame($.NSMakeRect(26,78,448,12));
    fields.progress.style = $.NSProgressIndicatorBarStyle; fields.progress.indeterminate = true;
    fields.progress.displayedWhenStopped = false; window.contentView.addSubview(fields.progress);
    fields.close = button('稍后','close:',20,90);
    fields.check = button('重新检查','check:',112,120);
    fields.install = button('下载并安装','install:',310,170);
    var current = text($.NSBundle.bundleWithPath(installed).objectForInfoDictionaryKey('CFBundleShortVersionString')) || '1.0.0';
    controller = new GPUQUpdates.Controller({
        now:function () { return Date.now(); }, render:renderUpdate, cancel:cancelJobs,
        fetch:function (done) {
            curl(GPUQUpdates.feed + '?t=' + Date.now(),null,65536,function (error,out) {
                var value; try { value = JSON.parse(out); } catch (e) { error = '更新信息无效'; }
                done(error,value);
            });
        },
        operation:operation,
        ready:function () { return Boolean(workDir && $.NSFileManager.defaultManager.fileExistsAtPath(workDir + '/ready')); },
        quitWidget:function () { oldWidgets = matchingWidgets(); oldWidgets.forEach(function (old) { old.terminate; }); },
        widgetStopped:function () { return oldWidgets.every(function (old) { return old.terminated; }) && matchingWidgets().length === 0; },
        permit:function () { writeFile(workDir + '/continue','install'); }
    },current);
    window.center; window.makeKeyAndOrderFront(null); app.activateIgnoringOtherApps(true);
    timer = $.NSTimer.scheduledTimerWithTimeIntervalTargetSelectorUserInfoRepeats(.25,target,'tick:',null,true);
    controller.check();
}
function reopen() { run(); }
