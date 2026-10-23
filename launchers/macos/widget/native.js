/* Private-file NSTask I/O shared by the widget and updater. */
var jobs = [];
function text(value) { return ObjC.unwrap(value) || ''; }
function readFile(path) {
    var value = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, null);
    return value.isNil() ? '' : text(value).replace(/\s+$/, '');
}
function writeFile(path, value) {
    $(String(value)).writeToFileAtomicallyEncodingError(path, true, $.NSUTF8StringEncoding, null);
}
var sequence = 0;
function removeJobFiles(job) {
    try { job.output.closeFile; } catch (error) {}
    try { job.errors.closeFile; } catch (error) {}
    $.NSFileManager.defaultManager.removeItemAtPathError(job.outPath, null);
    $.NSFileManager.defaultManager.removeItemAtPathError(job.errPath, null);
}
function process(path, args, callback) {
    var task = $.NSTask.alloc.init;
    var base = stateDir + '/widget-process-' + $.NSProcessInfo.processInfo.processIdentifier + '-' + (++sequence);
    var outPath = base + '.out', errPath = base + '.err';
    // A state response may contain large logs. Files avoid filling a pipe while
    // the AppKit main thread waits for task completion.
    [outPath,errPath].forEach(function (file) {
        $.NSFileManager.defaultManager.createFileAtPathContentsAttributes(file, null, $({NSFilePosixPermissions:384}));
    });
    var output = $.NSFileHandle.fileHandleForWritingAtPath(outPath);
    var errors = $.NSFileHandle.fileHandleForWritingAtPath(errPath);
    task.launchPath = path; task.arguments = args;
    var input = $.NSFileHandle.fileHandleForReadingAtPath('/dev/null');
    task.standardInput = input;
    task.standardOutput = output; task.standardError = errors;
    var entry = {task:task, output:output, errors:errors, outPath:outPath, errPath:errPath, callback:callback};
    try { task.launch; input.closeFile; } catch (error) {
        try { input.closeFile; } catch (ignored) {}
        removeJobFiles(entry); throw error;
    }
    jobs.push(entry); return entry;
}
function pump() {
    var finished = [];
    jobs = jobs.filter(function (job) {
        if (job.task.running) return true;
        finished.push(job); return false;
    });
    finished.forEach(function (job) {
        job.output.closeFile; job.errors.closeFile;
        var out = readFile(job.outPath), err = readFile(job.errPath);
        removeJobFiles(job);
        if (job.callback) job.callback(job.task.terminationStatus, out, err);
    });
}
