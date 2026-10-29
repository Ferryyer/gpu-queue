import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/notes.dart';

typedef CalendarDownload = Future<bool> Function(Directory cache, String day);
typedef CalendarNotesDownload = Future<String?> Function(String day);

/// No agent or external scheduler: the app calls its own packaged script.
class CalendarUpdater {
  CalendarUpdater(this.source, {CalendarDownload? download, CalendarNotesDownload? downloadNotes})
    : _download = download ?? _runScript, _downloadNotes = downloadNotes ?? CalendarNotes.fetch;
  final LocalCalendar source;
  final CalendarDownload _download;
  final CalendarNotesDownload _downloadNotes;
  CalendarReading? reading;
  DateTime? _lastAttempt;
  DateTime? _lastNotesAttempt;
  String? _lastNotesDate;
  Future<void>? _pending;

  Duration nextCheck(DateTime now) {
    final nextDay = DateTime.parse('${CalendarReading.day(now)}T00:01:00+08:00').add(const Duration(days: 1));
    var retry = reading?.updatedToday(now) == true ? nextDay
      : (_lastAttempt?.add(const Duration(minutes: 30)) ?? now);
    if (reading != null && !reading!.hasResearchNotes) {
      final notesRetry = _lastNotesDate != reading!.date ? now
        : _lastNotesAttempt?.add(const Duration(minutes: 30)) ?? now;
      if (notesRetry.isBefore(retry)) retry = notesRetry;
    }
    final due = retry.isBefore(nextDay) ? retry : nextDay;
    return due.isAfter(now) ? due.difference(now) : Duration.zero;
  }

  Future<void> loadCache(DateTime now) async {
    final cached = await source.readLatest(now);
    if (cached == null) return;
    if (cached.date != reading?.date) { reading = cached; return; }
    if (cached.notes != reading?.notes || cached.hasResearchNotes != reading?.hasResearchNotes) {
      reading = CalendarReading(bytes: reading!.bytes, date: cached.date,
        notes: cached.notes, hasResearchNotes: cached.hasResearchNotes);
    }
  }

  Future<void> update(DateTime now, {bool force = false}) {
    if (_pending != null) return _pending!;
    return _pending = _update(now, force: force).whenComplete(() => _pending = null);
  }

  Future<void> _update(DateTime now, {required bool force}) async {
    await loadCache(now);
    if (reading?.updatedToday(now) != true && (force || _lastAttempt == null ||
        now.difference(_lastAttempt!) >= const Duration(minutes: 30) ||
        CalendarReading.day(_lastAttempt!) != CalendarReading.day(now))) {
      _lastAttempt = now;
      try {
        if (await _download(source.directory, CalendarReading.day(now))) await loadCache(now);
      } on Exception { /* Keep valid cached content when offline. */ }
    }
    final current = reading;
    if (current == null || (!force && current.hasResearchNotes)) return;
    if (!force && _lastNotesAttempt != null &&
        _lastNotesDate == current.date &&
        now.difference(_lastNotesAttempt!) < const Duration(minutes: 30) &&
        CalendarReading.day(_lastNotesAttempt!) == CalendarReading.day(now)) {
      return;
    }
    _lastNotesAttempt = now;
    _lastNotesDate = current.date;
    try {
      final body = await _downloadNotes(current.date);
      if (body == null) return;
      final content = '${CalendarNotes.marker(current.date)}\n$body\n';
      if (CalendarNotes.parse(utf8.encode(content), current.date) == null) return;
      final temp = File('${source.directory.path}/${current.date}.notes.tmp');
      await temp.writeAsString(content, flush: true);
      await temp.rename('${source.directory.path}/${current.date}.notes.md');
      await loadCache(now);
    } on Exception { /* Missing editorial notes must not invalidate the image. */ }
  }

  static Future<bool> _runScript(Directory cache, String day) async {
    if (!Platform.isMacOS) return false;
    final contents = File(Platform.resolvedExecutable).parent.parent.path;
    final script = '$contents/Helpers/UpdateDailyCalendar';
    final checker = '$contents/Helpers/CalendarCheck';
    final process = await Process.start('/bin/bash', [script, cache.path, day, checker]);
    // Drain output without retaining a potentially unbounded log in memory.
    final stdout = process.stdout.drain<void>();
    final stderr = process.stderr.transform(utf8.decoder).drain<void>();
    try {
      return await process.exitCode.timeout(const Duration(seconds: 75)) == 0;
    } on TimeoutException {
      process.kill(ProcessSignal.sigkill);
      return false;
    } finally {
      await Future.wait([stdout, stderr]);
    }
  }
}
