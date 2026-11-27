import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:test/test.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/updater.dart';
import 'package:server_box/core/calendar/notes.dart';

void main() {
  late Directory dir;
  late DateTime now;
  Future<void> image(String day, [int version = 1]) async {
    await File(
      '${dir.path}/$day.jpg',
    ).writeAsBytes([0xff, 0xd8, version, 0xff, 0xd9]);
  }

  Future<void> snapshot(String day, String version, int value) async {
    final revision = 'snapshot-$day.$version';
    final folder = await Directory('${dir.path}/$revision').create();
    await File(
      '${folder.path}/image.jpg',
    ).writeAsBytes([0xff, 0xd8, value, 0xff, 0xd9]);
    await File(
      '${folder.path}/source.md',
    ).writeAsString('source $version for $day');
    await File('${dir.path}/$day.current').writeAsString(revision);
  }

  CalendarUpdater updater(
    CalendarDownload download, {
    CalendarNotesDownload? notes,
  }) => CalendarUpdater(
    LocalCalendar(dir),
    clock: () => now,
    download: download,
    downloadNotes: notes ?? (_) async => null,
  );
  setUp(() async {
    dir = await Directory.systemTemp.createTemp('inspire-calendar-test-');
    now = DateTime.utc(2026, 10, 29, 2);
  });
  tearDown(() async {
    await dir.delete(recursive: true);
  });

  test('Shanghai printed day crosses month and year boundaries', () {
    final reading = CalendarReading(bytes: Uint8List(0), date: '2026-10-28');
    expect(reading.updatedToday(DateTime.utc(2026, 10, 28, 15, 59)), isTrue);
    expect(reading.updatedToday(DateTime.utc(2026, 10, 28, 16)), isFalse);
    expect(CalendarReading.day(DateTime.utc(2026, 12, 31, 16)), '2027-01-01');
  });

  test(
    'missing, truncated and future files preserve last usable legacy image',
    () async {
      final source = LocalCalendar(dir);
      expect(await source.readLatest(now), isNull);
      await image('2026-10-28');
      await image('2026-10-30');
      await File('${dir.path}/2026-10-29.jpg').writeAsBytes([0xff, 0xd8, 0, 0]);
      await File('${dir.path}/2026-10-28.jpg').setLastModified(now);
      expect((await source.readLatest(now))?.date, '2026-10-28');
      expect((await source.readLatest(now))?.updatedToday(now), isFalse);
    },
  );

  test(
    'legacy provenance cannot borrow other dates or malformed text',
    () async {
      final source = LocalCalendar(dir);
      await image('2026-10-29');
      await File('${dir.path}/2026-10-28.md').writeAsString('old author');
      expect((await source.readLatest(now))?.notes, isNull);
      final note = File('${dir.path}/2026-10-29.md');
      await note.writeAsString('source');
      expect((await source.readLatest(now))?.notes, 'source');
      await note.writeAsBytes([0xff, 0xff]);
      expect((await source.readLatest(now))?.notes, isNull);
    },
  );

  test(
    'resume and manual refresh fetch even with today cached; timers recheck revisions',
    () async {
      await image('2026-10-29');
      var calls = 0;
      final subject = updater((_, day) async {
        await image(day, ++calls);
        return true;
      });
      await subject.update(now, force: true);
      await subject.update(now, force: true);
      expect(calls, 2);
      expect(subject.reading!.bytes[2], 2);
      expect(subject.latestCheckSucceeded, isTrue);
      await subject.update(now);
      expect(calls, 2);
      now = now.add(const Duration(minutes: 30));
      await subject.update(now);
      expect(calls, 3);
      expect(subject.reading!.bytes[2], 3);
      expect(subject.nextCheck(now), const Duration(minutes: 30));
    },
  );

  test(
    'today cached plus offline is a failed check; manual recovery bypasses cooldown',
    () async {
      await image('2026-10-29');
      var calls = 0, online = false;
      final subject = updater((_, day) async {
        calls++;
        if (!online) throw const SocketException('offline');
        await image(day, 9);
        return true;
      });
      await subject.update(now, force: true);
      expect(subject.reading!.date, '2026-10-29');
      expect(subject.latestCheckSucceeded, isFalse);
      await subject.update(now);
      expect(calls, 1);
      online = true;
      await subject.update(now, force: true);
      expect(calls, 2);
      expect(subject.reading!.bytes[2], 9);
      expect(subject.latestCheckSucceeded, isTrue);
    },
  );

  test('failed revalidation cannot retain an earlier success status', () async {
    var success = true;
    final subject = updater((_, day) async {
      if (success) await image(day);
      return success;
    });
    await subject.update(now, force: true);
    expect(subject.latestCheckSucceeded, isTrue);
    success = false;
    await subject.update(now, force: true);
    expect(subject.latestCheckSucceeded, isFalse);
    expect(subject.reading!.date, '2026-10-29');
  });

  test(
    'parallel ticks coalesce; repeated explicit refresh queues a serialized new check',
    () async {
      final started = Completer<void>(), finish = Completer<void>();
      var calls = 0, running = 0;
      final subject = updater((_, day) async {
        expect(++running, 1);
        final version = ++calls;
        if (version == 1) {
          started.complete();
          await finish.future;
        }
        await snapshot(day, 'v$version', version);
        running--;
        return true;
      });
      final first = subject.update(now);
      await started.future;
      final ordinary = subject.update(now);
      final second = subject.update(now, force: true);
      final third = subject.update(now, force: true);
      expect(calls, 1);
      finish.complete();
      await Future.wait([first, ordinary, second, third]);
      expect(calls, 2);
      expect(subject.reading!.bytes[2], 2);
      expect(subject.reading!.notes, 'source v2 for 2026-10-29');
    },
  );

  test(
    'download crossing Shanghai midnight immediately fetches new day',
    () async {
      now = DateTime.utc(2026, 12, 31, 15, 59);
      final days = <String>[];
      final subject = updater((_, day) async {
        days.add(day);
        await image(day);
        if (days.length == 1) now = DateTime.utc(2026, 12, 31, 16);
        return true;
      });
      await subject.update(now, force: true);
      expect(days, ['2026-12-31', '2027-01-01']);
      expect(subject.reading!.date, '2027-01-01');
      expect(subject.latestCheckSucceeded, isTrue);
    },
  );

  test(
    'absent notes crossing midnight cannot delay the next image check',
    () async {
      now = DateTime.utc(2026, 10, 29, 15, 59);
      final days = <String>[];
      final subject = updater(
        (_, day) async {
          days.add(day);
          await image(day);
          return true;
        },
        notes: (_) async {
          now = DateTime.utc(2026, 10, 29, 16);
          return null;
        },
      );
      await subject.update(now);
      expect(days, ['2026-10-29', '2026-10-30']);
      expect(subject.reading!.date, '2026-10-30');
    },
  );

  test('unpublished new day keeps yesterday and remains retryable', () async {
    await image('2026-10-28');
    var calls = 0;
    final subject = updater((_, _) async {
      calls++;
      return false;
    });
    await subject.update(now);
    await subject.update(now, force: true);
    expect(calls, 2);
    expect(subject.reading!.date, '2026-10-28');
    expect(subject.latestCheckSucceeded, isFalse);
    now = DateTime.utc(2026, 10, 29, 15, 59);
    await subject.update(now);
    expect(subject.nextCheck(now), const Duration(minutes: 2));
  });

  test(
    'atomic snapshot binds image and source and isolates notes by revision',
    () async {
      await snapshot('2026-10-29', 'v1', 1);
      var published = true;
      final subject = updater(
        (_, _) async => false,
        notes: (_) async => published ? '# Verified source' : null,
      );
      await subject.update(now, force: true);
      expect(subject.reading!.hasResearchNotes, isTrue);
      final restart = updater((_, _) async => false);
      await restart.loadCache(now);
      expect(restart.reading!.notes, '# Verified source');
      expect(restart.reading!.imageSource, 'source v1 for 2026-10-29');
      // An incomplete unpublished revision must not affect the current pointer.
      await Directory('${dir.path}/snapshot-2026-10-29.v2').create();
      await restart.loadCache(now);
      expect(restart.reading!.bytes[2], 1);
      published = false;
      await snapshot('2026-10-29', 'v2', 2);
      await subject.update(now, force: true);
      expect(subject.reading!.bytes[2], 2);
      expect(subject.reading!.notes, 'source v2 for 2026-10-29');
      expect(subject.reading!.hasResearchNotes, isFalse);
    },
  );

  test(
    'invalid snapshot pointers cannot escape cache or hide usable old data',
    () async {
      await image('2026-10-28');
      await File(
        '${dir.path}/2026-10-29.current',
      ).writeAsString('../elsewhere');
      expect((await LocalCalendar(dir).readLatest(now))!.date, '2026-10-28');
      await File(
        '${dir.path}/2026-10-29.current',
      ).writeAsString('snapshot-2026-10-28.v1');
      expect((await LocalCalendar(dir).readLatest(now))!.date, '2026-10-28');
    },
  );

  test('late cache reads cannot overwrite a newer image and source', () async {
    final source = _DelayedCalendar(dir);
    final subject = CalendarUpdater(source, clock: () => now);
    final oldRequest = subject.loadCache(now);
    final newRequest = subject.loadCache(now);
    final newer = CalendarReading(
      bytes: Uint8List.fromList([2]),
      date: '2026-10-29',
      notes: 'new source',
    );
    source.requests[1].complete(newer);
    await newRequest;
    source.requests[0].complete(
      CalendarReading(
        bytes: Uint8List.fromList([1]),
        date: '2026-10-29',
        notes: 'old source',
      ),
    );
    await oldRequest;
    expect(subject.reading!.bytes, newer.bytes);
    expect(subject.reading!.notes, 'new source');
  });

  test('published notes require exact date and bounded non-HTML text', () {
    final note = '${CalendarNotes.marker("2026-10-29")}\n# Test\nSource';
    expect(
      CalendarNotes.parse(utf8.encode(note), '2026-10-29'),
      '# Test\nSource',
    );
    expect(CalendarNotes.parse(utf8.encode(note), '2026-10-28'), isNull);
    expect(
      CalendarNotes.parse(utf8.encode('$note<script>'), '2026-10-29'),
      isNull,
    );
    expect(CalendarNotes.parse(List.filled(65537, 65), '2026-10-29'), isNull);
  });
}

class _DelayedCalendar extends LocalCalendar {
  _DelayedCalendar(super.directory);
  final requests = <Completer<CalendarReading?>>[];
  @override
  Future<CalendarReading?> readLatest(DateTime now) {
    final request = Completer<CalendarReading?>();
    requests.add(request);
    return request.future;
  }
}
