import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:server_box/core/calendar/local_calendar.dart';

typedef CalendarDownload = Future<bool> Function(Directory cache, String day);

/// No agent or external scheduler: the app calls its own packaged script.
class CalendarUpdater {
  CalendarUpdater(this.source, {CalendarDownload? download}) : _download = download ?? _runScript;
  final LocalCalendar source;
  final CalendarDownload _download;
  CalendarReading? reading;
  DateTime? _lastAttempt;
  Future<void>? _pending;

  Duration nextCheck(DateTime now) {
    final nextDay = DateTime.parse('${CalendarReading.day(now)}T00:01:00+08:00').add(const Duration(days: 1));
    final retry = reading?.updatedToday(now) == true ? nextDay
      : (_lastAttempt?.add(const Duration(minutes: 30)) ?? now);
    final due = retry.isBefore(nextDay) ? retry : nextDay;
    return due.isAfter(now) ? due.difference(now) : Duration.zero;
  }

  Future<void> loadCache(DateTime now) async {
    final cached = await source.readLatest(now);
    if (cached != null && cached.date != reading?.date) reading = cached;
  }

  Future<void> update(DateTime now, {bool force = false}) {
    if (_pending != null) return _pending!;
    return _pending = _update(now, force: force).whenComplete(() => _pending = null);
  }

  Future<void> _update(DateTime now, {required bool force}) async {
    await loadCache(now);
    if (reading?.updatedToday(now) == true) return;
    if (!force && nextCheck(now) > Duration.zero) return;
    _lastAttempt = now;
    try {
      if (await _download(source.directory, CalendarReading.day(now))) await loadCache(now);
    } on Exception {
      // Network/host problems preserve the last valid day. The UI reports stale
      // content and the next attempt is throttled, including after app resume.
    }
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
