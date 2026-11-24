import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/notes.dart';

typedef CalendarDownload = Future<bool> Function(Directory cache, String day);

/// The complete published document, including its date and image binding.
typedef CalendarNotesDownload = Future<String?> Function(String day);

/// No agent or external scheduler: the app calls its own packaged script.
class CalendarUpdater {
  CalendarUpdater(
    this.source, {
    CalendarDownload? download,
    CalendarNotesDownload? downloadNotes,
    DateTime Function()? clock,
  }) : _download = download ?? _runScript,
       _downloadNotes = downloadNotes ?? CalendarNotes.fetch,
       _clock = clock ?? DateTime.now;
  final LocalCalendar source;
  final CalendarDownload _download;
  final CalendarNotesDownload _downloadNotes;
  final DateTime Function() _clock;
  CalendarReading? reading;

  /// A dated cache alone is not evidence that this check reached the publisher.
  bool latestCheckSucceeded = false;
  DateTime? _lastAttempt;
  DateTime? _lastNotesAttempt;
  String? _lastNotesDate;
  Future<void>? _pending;
  bool _requested = false, _forceRequested = false;

  // Also serialize across panel disposal/recreation. A late old process must
  // finish before a new instance can publish to the same cache directory.
  static final _writers = <String, Future<void>>{};
  Future<void> _serialized(Future<void> Function() action) async {
    final key = source.directory.absolute.path;
    final previous = _writers[key];
    final done = Completer<void>();
    _writers[key] = done.future;
    if (previous != null) await previous;
    try {
      await action();
    } finally {
      done.complete();
      if (identical(_writers[key], done.future)) _writers.remove(key);
    }
  }

  Duration nextCheck(DateTime now) {
    final nextDay = DateTime.parse('${CalendarReading.day(now)}T00:01:00+08:00')
        .add(const Duration(days: 1));
    var retry = latestCheckSucceeded && reading?.updatedToday(now) == true
        ? nextDay
        : (_lastAttempt?.add(const Duration(minutes: 30)) ?? now);
    if (reading != null && !reading!.hasResearchNotes) {
      final notesRetry = _lastNotesDate != reading!.date
          ? now
          : _lastNotesAttempt?.add(const Duration(minutes: 30)) ?? now;
      if (notesRetry.isBefore(retry)) retry = notesRetry;
    }
    final due = retry.isBefore(nextDay) ? retry : nextDay;
    return due.isAfter(now) ? due.difference(now) : Duration.zero;
  }

  Future<void> loadCache() => _serialized(_loadCache);

  Future<void> _loadCache() async {
    final cached = await source.readLatest(_clock());
    if (cached == null) return;
    final old = reading;
    if (old == null ||
        cached.date != old.date ||
        !_sameBytes(cached.bytes, old.bytes)) {
      reading = cached;
    } else if (cached.notes != old.notes ||
        cached.hasResearchNotes != old.hasResearchNotes) {
      reading = CalendarReading(
        bytes: old.bytes,
        date: cached.date,
        notes: cached.notes,
        hasResearchNotes: cached.hasResearchNotes,
      );
    }
  }

  static bool _sameBytes(List<int> a, List<int> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }

  Future<void> update({bool force = false}) {
    _requested = true;
    _forceRequested |= force;
    return _pending ??= _drain();
  }

  Future<void> _drain() async {
    try {
      while (_requested) {
        await _serialized(() async {
          final force = _forceRequested;
          _requested = _forceRequested = false;
          final day = CalendarReading.day(_clock());
          await _update(force: force);
          // A request straddling Beijing midnight cannot count as today's check.
          if (CalendarReading.day(_clock()) != day) {
            _requested = _forceRequested = true;
          }
        });
      }
    } finally {
      _pending = null;
    }
  }

  Future<void> _update({required bool force}) async {
    await _loadCache();
    final now = _clock();
    if (force ||
        _lastAttempt == null ||
        now.difference(_lastAttempt!) >= const Duration(minutes: 30) ||
        CalendarReading.day(_lastAttempt!) != CalendarReading.day(now)) {
      _lastAttempt = now;
      latestCheckSucceeded = false;
      try {
        final success = await _download(
          source.directory,
          CalendarReading.day(now),
        );
        await _loadCache();
        latestCheckSucceeded =
            success && reading?.updatedToday(_clock()) == true;
      } on Exception {
        /* Keep valid cached content when offline. */
      }
    }
    final current = reading;
    if (current == null || (!force && current.hasResearchNotes)) return;
    if (!force &&
        _lastNotesAttempt != null &&
        _lastNotesDate == current.date &&
        now.difference(_lastNotesAttempt!) < const Duration(minutes: 30) &&
        CalendarReading.day(_lastNotesAttempt!) == CalendarReading.day(now)) {
      return;
    }
    _lastNotesAttempt = now;
    _lastNotesDate = current.date;
    try {
      final content = await _downloadNotes(current.date);
      if (content == null) return;
      if (CalendarNotes.parse(
            utf8.encode(content),
            current.date,
            imageSha256: sha256.convert(current.bytes).toString(),
          ) ==
          null)
        return;
      final temp = File('${source.directory.path}/${current.date}.notes.tmp');
      await temp.writeAsString(content, flush: true);
      await temp.rename('${source.directory.path}/${current.date}.notes.md');
      await _loadCache();
    } on Exception {
      /* Missing editorial notes must not invalidate the image. */
    }
  }

  static Future<bool> _runScript(Directory cache, String day) async {
    if (!Platform.isMacOS) return false;
    final contents = File(Platform.resolvedExecutable).parent.parent.path;
    final script = '$contents/Helpers/UpdateDailyCalendar';
    final checker = '$contents/Helpers/CalendarCheck';
    final process = await Process.start('/bin/bash', [
      script,
      cache.path,
      day,
      checker,
    ]);
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
