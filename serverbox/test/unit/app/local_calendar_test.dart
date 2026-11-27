import 'dart:async';
import 'dart:io';
import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:server_box/core/calendar/local_calendar.dart';
import 'package:server_box/core/calendar/updater.dart';
import 'package:server_box/core/calendar/notes.dart';

void main() {
  late Directory dir;
  final now = DateTime.utc(2026, 10, 29, 2);
  late DateTime clock;
  final oldBytes = [0xff, 0xd8, 1, 0xff, 0xd9];
  final revisedBytes = [0xff, 0xd8, 2, 0xff, 0xd9];
  Future<void> image(String day, [List<int>? bytes]) async {
    await File('${dir.path}/$day.jpg').writeAsBytes(bytes ?? oldBytes);
  }

  Future<void> manifest(String day, List<int> bytes, {String? url}) async {
    final digest = sha256.convert(bytes).toString();
    await File('${dir.path}/$day.$digest.jpg').writeAsBytes(bytes);
    await File('${dir.path}/$day.json').writeAsString(
      jsonEncode({
        'date': day,
        'sha256': digest,
        'source':
            url ??
            'https://img.owspace.com/Public/uploads/Download/2026/1029.jpg',
      }),
    );
  }

  String researchNote(String day, String body, [List<int>? bytes]) =>
      '${CalendarNotes.marker(day)}\n${CalendarNotes.imageMarker(sha256.convert(bytes ?? oldBytes).toString())}\n$body\n';

  CalendarUpdater updater({
    CalendarDownload? download,
    CalendarNotesDownload? notes,
  }) => CalendarUpdater(
    LocalCalendar(dir),
    clock: () => clock,
    download: download ?? (_, _) async => false,
    downloadNotes: notes ?? (_) async => null,
  );

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('inspire-calendar-test-');
    clock = now;
  });
  tearDown(() async {
    await dir.delete(recursive: true);
  });

  test('Shanghai day uses printed date rather than file modification time', () {
    final reading = CalendarReading(bytes: Uint8List(0), date: '2026-10-28');
    expect(reading.updatedToday(DateTime.utc(2026, 10, 28, 15, 59)), isTrue);
    expect(reading.updatedToday(DateTime.utc(2026, 10, 28, 16)), isFalse);
    expect(CalendarReading.day(DateTime.utc(2026, 12, 31, 16)), '2027-01-01');
  });

  test(
    'missing, truncated and future files do not displace the last valid image',
    () async {
      final source = LocalCalendar(dir);
      expect(await source.readLatest(now), isNull);
      await image('2026-10-28');
      await image('2026-10-30');
      await image('2026-10-29', [0xff, 0xd8, 0, 0]);
      expect((await source.readLatest(now))?.date, '2026-10-28');
      await File('${dir.path}/2026-10-28.jpg').setLastModified(now);
      expect((await source.readLatest(now))?.updatedToday(now), isFalse);
    },
  );

  test('legacy provenance belongs to image date, malformed optional text is ignored', () async {
    final source = LocalCalendar(dir);
    await image('2026-10-29');
    await File('${dir.path}/2026-10-28.md').writeAsString('old author');
    expect((await source.readLatest(now))?.notes, isNull);
    final note = File('${dir.path}/2026-10-29.md');
    await note.writeAsString('source');
    expect((await source.readLatest(now))?.notes, 'source');
    await note.writeAsBytes([0xff, 0xff]);
    expect((await source.readLatest(now))?.notes, isNull);
  });

  test(
    'atomic manifest selects matching image and source over legacy cache',
    () async {
      await image('2026-10-29');
      await File('${dir.path}/2026-10-29.md').writeAsString('legacy source');
      const source =
          'https://img.owspace.com/Public/uploads/Download/2026/1030.jpg';
      await manifest('2026-10-29', revisedBytes, url: source);
      final reading = await LocalCalendar(dir).readLatest(now);
      expect(reading!.bytes, revisedBytes);
      expect(reading.notes, contains(source));
      expect(reading.notes, isNot(contains('legacy source')));
      // An uncommitted download cannot replace the manifest snapshot.
      await File('${dir.path}/2026-10-29.${'a' * 64}.jpg')
          .writeAsBytes(oldBytes);
      expect((await LocalCalendar(dir).readLatest(now))!.bytes, revisedBytes);
    },
  );

  test(
    'corrupt manifest, checksum mismatch and untrusted source fall back safely',
    () async {
      await image('2026-10-28');
      final path = File('${dir.path}/2026-10-29.json');
      for (final value in [
        'not json',
        '[]',
        '{"date":"2026-10-29","sha256":"../bad"}',
        'x' * 4097,
      ]) {
        await path.writeAsString(value);
        expect((await LocalCalendar(dir).readLatest(now))!.date, '2026-10-28');
      }
      await manifest(
        '2026-10-29',
        oldBytes,
        url: 'http://img.owspace.com/Public/uploads/Download/2026/1029.jpg',
      );
      expect((await LocalCalendar(dir).readLatest(now))!.date, '2026-10-28');
      await manifest('2026-10-29', oldBytes);
      await File('${dir.path}/2026-10-29.${sha256.convert(oldBytes)}.jpg')
          .writeAsBytes(revisedBytes);
      expect((await LocalCalendar(dir).readLatest(now))!.date, '2026-10-28');
    },
  );

  test("forced open and refresh revalidate today's cache and replace revised bytes", () async {
    await image('2026-10-29');
    var calls = 0;
    final subject = updater(
      download: (_, day) async {
        calls++;
        await manifest(day, calls == 1 ? oldBytes : revisedBytes);
        return true;
      },
    );
    await subject.update(force: true);
    final first = subject.reading;
    await subject.update(force: true);
    expect(calls, 2);
    expect(subject.reading!.bytes, revisedBytes);
    expect(subject.reading, isNot(same(first)));
    expect(subject.latestCheckSucceeded, isTrue);
  });

  for (final response in [
    'missing',
    'offline',
    'stale-bound',
    'stale-unbound',
  ]) {
    test(
      'CAL-A-001: same-day replacement rejects $response notes and survives restart',
      () async {
        const day = '2026-10-29';
        const sourceB =
            'https://img.owspace.com/Public/uploads/Download/2026/1030.jpg';
        final noteA = researchNote(
          day,
          '# Attribution A\n[Original A](https://example.com/a)',
        );
        final noteFile = File('${dir.path}/$day.notes.md');
        await manifest(day, oldBytes);
        await noteFile.writeAsString(noteA);
        final subject = updater(
          download: (_, requestedDay) async {
            await manifest(requestedDay, revisedBytes, url: sourceB);
            return true;
          },
          notes: (_) async {
            if (response == 'offline') throw const SocketException('offline');
            if (response == 'stale-bound') return noteA;
            if (response == 'stale-unbound')
              return '${CalendarNotes.marker(day)}\n# Attribution A\n';
            return null;
          },
        );
        await subject.loadCache();
        expect(subject.reading!.hasResearchNotes, isTrue);
        expect(subject.reading!.notes, contains('Attribution A'));

        await subject.update(force: true);
        expect(subject.reading!.bytes, revisedBytes);
        expect(subject.latestCheckSucceeded, isTrue);
        expect(subject.reading!.hasResearchNotes, isFalse);
        expect(subject.reading!.notes, contains(sourceB));
        expect(subject.reading!.notes, isNot(contains('Attribution A')));
        expect(
          await noteFile.readAsString(),
          noteA,
        ); // Preserve old evidence without displaying it for B.

        final offline = updater();
        await offline.update(force: true);
        expect(offline.reading!.hasResearchNotes, isFalse);
        expect(offline.reading!.notes, contains(sourceB));
        expect(offline.reading!.notes, isNot(contains('Attribution A')));
      },
    );
  }

  test('unbound legacy notes stay on disk but cannot replace a revised manifest source', () async {
    const day = '2026-10-29';
    const sourceB =
        'https://img.owspace.com/Public/uploads/Download/2026/1030.jpg';
    await image(day);
    final note = File('${dir.path}/$day.notes.md');
    final oldNote = '${CalendarNotes.marker(day)}\n# Unbound attribution A\n';
    await note.writeAsString(oldNote);
    await manifest(day, revisedBytes, url: sourceB);
    final reading = (await LocalCalendar(dir).readLatest(now))!;
    expect(reading.bytes, revisedBytes);
    expect(reading.hasResearchNotes, isFalse);
    expect(reading.notes, contains(sourceB));
    expect(reading.notes, isNot(contains('Unbound attribution A')));
    expect(await note.readAsString(), oldNote);
  });

  test(
    'matching B notes can replace A notes without reloading B image bytes',
    () async {
      const day = '2026-10-29';
      await manifest(day, revisedBytes);
      await File('${dir.path}/$day.notes.md')
          .writeAsString(researchNote(day, '# A'));
      final subject = updater(
        notes: (date) async => researchNote(date, '# B', revisedBytes),
      );
      await subject.loadCache();
      final bytes = subject.reading!.bytes;
      expect(subject.reading!.hasResearchNotes, isFalse);
      await subject.update(force: true);
      expect(subject.reading!.notes, '# B');
      expect(subject.reading!.hasResearchNotes, isTrue);
      expect(subject.reading!.bytes, same(bytes));
      expect((await LocalCalendar(dir).readLatest(now))!.notes, '# B');
    },
  );

  test('note binding requires the exact image digest and rejects legacy and malformed bindings', () {
    const day = '2026-10-29';
    final digestA = sha256.convert(oldBytes).toString();
    final digestB = sha256.convert(revisedBytes).toString();
    final document = researchNote(day, '# A');
    expect(
      CalendarNotes.parse(utf8.encode(document), day, imageSha256: digestA),
      '# A',
    );
    expect(
      CalendarNotes.parse(utf8.encode(document), day, imageSha256: digestB),
      isNull,
    );
    expect(
      CalendarNotes.parse(
        utf8.encode('${CalendarNotes.marker(day)}\n# Unbound'),
        day,
        imageSha256: digestA,
      ),
      isNull,
    );
    for (final broken in [
      document.replaceFirst(digestA, '../bad'),
      document.replaceFirst(digestA, digestA.toUpperCase()),
      document.replaceFirst(day, '2026-10-28'),
      '$document<script>',
    ]) {
      expect(
        CalendarNotes.parse(utf8.encode(broken), day, imageSha256: digestA),
        isNull,
      );
    }
  });

  test('unmodified bytes are reused while notes can change', () async {
    await image('2026-10-29');
    var note = '# First';
    final subject = updater(
      download: (_, _) async => true,
      notes: (day) async => researchNote(day, note),
    );
    await subject.update(force: true);
    final bytes = subject.reading!.bytes;
    note = '# Revision';
    await subject.update(force: true);
    expect(subject.reading!.notes, '# Revision');
    expect(subject.reading!.bytes, same(bytes));
  });

  test(
    "offline preserves today's cache but cannot report fresh-check success",
    () async {
      await image('2026-10-29');
      var online = true, calls = 0;
      final subject = updater(
        download: (_, _) async {
          calls++;
          if (!online) throw const SocketException('offline');
          return true;
        },
        notes: (day) async => researchNote(day, '# Cached source'),
      );
      await subject.update(force: true);
      expect(subject.latestCheckSucceeded, isTrue);
      online = false;
      await subject.update(force: true);
      expect(subject.reading!.date, '2026-10-29');
      expect(subject.latestCheckSucceeded, isFalse);
      expect(subject.nextCheck(clock), const Duration(minutes: 30));
      clock = now.add(const Duration(minutes: 1));
      await subject.update();
      expect(calls, 2);
      online = true;
      await subject.update(force: true);
      expect(calls, 3);
      expect(subject.latestCheckSucceeded, isTrue);
    },
  );

  test('upstream unavailable keeps old date, automatic retry backs off, explicit retry bypasses it', () async {
    await image('2026-10-28');
    var online = false, calls = 0;
    final subject = updater(
      download: (_, day) async {
        calls++;
        if (!online) return false;
        await image(day);
        return true;
      },
    );
    await subject.update();
    final cached = subject.reading;
    expect(cached!.date, '2026-10-28');
    expect(subject.latestCheckSucceeded, isFalse);
    clock = now.add(const Duration(minutes: 1));
    await subject.update();
    expect(calls, 1);
    expect(subject.reading, same(cached));
    online = true;
    await subject.update(force: true);
    expect(calls, 2);
    expect(subject.reading!.date, '2026-10-29');
  });

  test(
    "a claimed download without today's valid image is not a success",
    () async {
      await image('2026-10-28');
      final subject = updater(
        download: (_, day) async {
          await image(day, utf8.encode('<html>not an image</html>'));
          return true;
        },
      );
      await subject.update(force: true);
      expect(subject.reading!.date, '2026-10-28');
      expect(subject.latestCheckSucceeded, isFalse);
    },
  );

  test('refresh burst queues one real followup and cannot publish in reverse order', () async {
    final started = Completer<void>(), release = Completer<void>();
    var calls = 0, running = 0, maximum = 0;
    final subject = updater(
      download: (_, day) async {
        calls++;
        running++;
        if (running > maximum) maximum = running;
        if (calls == 1) {
          started.complete();
          await release.future;
        }
        await manifest(day, calls == 1 ? oldBytes : revisedBytes);
        running--;
        return true;
      },
    );
    final first = subject.update(force: true);
    await started.future;
    final rest = List.generate(20, (_) => subject.update(force: true));
    release.complete();
    await Future.wait([first, ...rest]);
    expect(calls, 2);
    expect(maximum, 1);
    expect(subject.reading!.bytes, revisedBytes);
    expect((await LocalCalendar(dir).readLatest(clock))!.bytes, revisedBytes);
  });

  test(
    'recreated updater waits for old writer before publishing its revision',
    () async {
      final started = Completer<void>(), release = Completer<void>();
      final order = <int>[];
      final old = updater(
        download: (_, day) async {
          started.complete();
          await release.future;
          await manifest(day, oldBytes);
          order.add(1);
          return true;
        },
      );
      final newer = updater(
        download: (_, day) async {
          await manifest(day, revisedBytes);
          order.add(2);
          return true;
        },
      );
      final first = old.update(force: true);
      await started.future;
      final second = newer.update(force: true);
      await Future<void>.delayed(Duration.zero);
      expect(order, isEmpty);
      release.complete();
      await Future.wait([first, second]);
      expect(order, [1, 2]);
      expect(newer.reading!.bytes, revisedBytes);
    },
  );

  test(
    'midnight during a slow request checks new Beijing date before completing',
    () async {
      clock = DateTime.utc(2026, 12, 31, 15, 59);
      final days = <String>[];
      final subject = updater(
        download: (_, day) async {
          days.add(day);
          if (days.length == 1) clock = DateTime.utc(2026, 12, 31, 16);
          await image(day);
          return true;
        },
      );
      await subject.update(force: true);
      expect(days, ['2026-12-31', '2027-01-01']);
      expect(subject.reading!.date, '2027-01-01');
      expect(subject.latestCheckSucceeded, isTrue);
    },
  );

  test(
    'new date bypasses cooldown and next check crosses the year boundary',
    () async {
      clock = DateTime.utc(2026, 12, 31, 15, 59);
      final days = <String>[];
      final subject = updater(
        download: (_, day) async {
          days.add(day);
          await image(day);
          return true;
        },
        notes: (day) async => researchNote(day, '# Verified'),
      );
      await subject.update();
      expect(subject.nextCheck(clock), const Duration(minutes: 2));
      clock = DateTime.utc(2026, 12, 31, 16, 1);
      await subject.update();
      expect(days, ['2026-12-31', '2027-01-01']);
    },
  );

  test(
    'published notes match image day and cannot load HTML or oversize content',
    () {
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
    },
  );

  test(
    'late notes retain bytes, retry on schedule and survive offline restart',
    () async {
      await image('2026-10-29');
      var published = false, requests = 0;
      final subject = updater(
        download: (_, _) async => true,
        notes: (day) async {
          expect(day, '2026-10-29');
          requests++;
          return published ? researchNote(day, '# Verified source') : null;
        },
      );
      await subject.update();
      final bytes = subject.reading!.bytes;
      published = true;
      clock = now.add(const Duration(minutes: 2));
      await subject.update();
      expect(requests, 1);
      clock = now.add(const Duration(minutes: 30));
      await subject.update();
      expect(subject.reading!.hasResearchNotes, isTrue);
      expect(subject.reading!.bytes, same(bytes));
      final offline = updater(
        notes: (_) async => throw const SocketException('offline'),
      );
      await offline.update();
      expect(offline.reading!.notes, '# Verified source');
      expect(offline.latestCheckSucceeded, isFalse);
      expect(offline.nextCheck(clock), const Duration(minutes: 30));
    },
  );
}
