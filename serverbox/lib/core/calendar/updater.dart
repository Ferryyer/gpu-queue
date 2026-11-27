import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/notes.dart';

typedef CalendarDownload = Future<bool> Function(Directory cache, String day);
typedef CalendarNotesDownload = Future<String?> Function(String day);

/// The UI shares one updater across panel recreation, so downloads and commits
/// cannot race even if a previous panel is disposed while its script is running.
class CalendarUpdater {
  CalendarUpdater(
    this.source, {
    CalendarDownload? download,
    CalendarNotesDownload? downloadNotes,
    DateTime Function()? clock,
  }) : _download = download ?? _runScript,
       _downloadNotes = downloadNotes ?? CalendarNotes.fetch,
       _clock = clock ?? DateTime.now;
  static final _shared = <String, CalendarUpdater>{};
  static CalendarUpdater shared(LocalCalendar source) => _shared.putIfAbsent(
    source.directory.absolute.path,
    () => CalendarUpdater(source),
  );

  final LocalCalendar source;
  final CalendarDownload _download;
  final CalendarNotesDownload _downloadNotes;
  final DateTime Function() _clock;
  CalendarReading? reading;

  /// A same-day cached image is not evidence that this network check succeeded.
  bool latestCheckSucceeded = false;
  DateTime? _lastAttempt;
  DateTime? _lastNotesAttempt;
  String? _lastNotesRevision;
  Future<void>? _pending;
  DateTime? _queued;
  bool _queuedForce = false;
  int _cacheRead = 0;

  Duration nextCheck(DateTime now) {
    final nextDay = DateTime.parse(
      '${CalendarReading.day(now)}T00:01:00+08:00',
    ).add(const Duration(days: 1));
    // Periodically revalidate even today's image: the publisher can revise it.
    final retry = _lastAttempt?.add(const Duration(minutes: 30)) ?? now;
    final due = retry.isBefore(nextDay) ? retry : nextDay;
    return due.isAfter(now) ? due.difference(now) : Duration.zero;
  }

  Future<void> loadCache(DateTime now) async {
    final request = ++_cacheRead;
    final cached = await source.readLatest(now);
    if (request != _cacheRead) return;
    if (cached == null) return;
    final previous = reading;
    if (previous != null && cached.date.compareTo(previous.date) < 0) return;
    // Reuse decoded image bytes only when their contents are equal, not merely
    // because the date matches. Same-day revisions must reach Image.memory.
    final sameBytes =
        previous != null && _equalBytes(previous.bytes, cached.bytes);
    reading = CalendarReading(
      bytes: sameBytes ? previous.bytes : cached.bytes,
      date: cached.date,
      notes: cached.notes,
      imageSource: cached.imageSource,
      hasResearchNotes: cached.hasResearchNotes,
      revision: cached.revision,
    );
  }

  static bool _equalBytes(List<int> a, List<int> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }

  Future<void> update(DateTime now, {bool force = false}) {
    if (_pending != null) {
      // Ordinary simultaneous timer ticks share a check. An explicit refresh,
      // resume or new day always gets a follow-up check, never a dropped click.
      if (force ||
          CalendarReading.day(now) !=
              CalendarReading.day(_lastAttempt ?? now)) {
        if (_queued == null || now.isAfter(_queued!)) _queued = now;
        _queuedForce |= force;
      }
      return _pending!;
    }
    return _pending = _drain(now, force).whenComplete(() => _pending = null);
  }

  Future<void> _drain(DateTime now, bool force) async {
    while (true) {
      await _update(now, force: force);
      if (_queued == null) return;
      now = _queued!;
      force = _queuedForce;
      _queued = null;
      _queuedForce = false;
    }
  }

  Future<void> _update(DateTime now, {required bool force}) async {
    // Time may have advanced while this request was queued.
    now = _clock();
    await loadCache(now);
    final day = CalendarReading.day(now);
    if (force ||
        _lastAttempt == null ||
        now.difference(_lastAttempt!) >= const Duration(minutes: 30) ||
        CalendarReading.day(_lastAttempt!) != day) {
      _lastAttempt = now;
      latestCheckSucceeded = false;
      try {
        if (await _download(source.directory, day)) {
          await loadCache(_clock());
          latestCheckSucceeded = reading?.date == day;
        }
      } on Exception {
        /* Keep valid cached content when offline. */
      }
    }
    // A pre-midnight response cannot certify the new day. Finish the current
    // serialized operation, then immediately request the actual current day.
    final finished = _clock();
    if (CalendarReading.day(finished) != day) {
      latestCheckSucceeded = false;
      _queued = finished;
      _queuedForce = true;
      return;
    }
    await _updateNotes(now, force: force);
    // Notes can straddle midnight too, including an absent/offline response.
    if (CalendarReading.day(_clock()) != day) {
      latestCheckSucceeded = false;
      _queued = _clock();
      _queuedForce = true;
    }
  }

  Future<void> _updateNotes(DateTime now, {required bool force}) async {
    final current = reading;
    if (current == null) return;
    final identity = current.revision ?? current.date;
    if (!force &&
        _lastNotesAttempt != null &&
        _lastNotesRevision == identity &&
        now.difference(_lastNotesAttempt!) < const Duration(minutes: 30))
      return;
    _lastNotesAttempt = now;
    _lastNotesRevision = identity;
    try {
      final body = await _downloadNotes(current.date);
      if (body == null) return;
      final content = '${CalendarNotes.marker(current.date)}\n$body\n';
      if (CalendarNotes.parse(utf8.encode(content), current.date) == null)
        return;
      final target = source.notesFile(current.date, current.revision);
      final temp = File('${target.path}.tmp');
      await temp.writeAsString(content, flush: true);
      await temp.rename(target.path);
      await loadCache(_clock());
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
    final stdout = process.stdout.listen((_) {});
    final stderr = process.stderr.listen((_) {});
    try {
      return await process.exitCode.timeout(const Duration(seconds: 75)) == 0;
    } on TimeoutException {
      process.kill(ProcessSignal.sigkill);
      return false;
    } finally {
      // A timed-out shell may leave an OCR/curl child holding a pipe open.
      // Cancel the readers instead of waiting indefinitely for inherited EOF.
      await Future.wait([stdout.cancel(), stderr.cancel()]);
    }
  }
}
